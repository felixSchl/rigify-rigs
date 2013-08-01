"""
Creates a chain of Spring-constrained bones with controls.

Brief overview of technique:
1 chain of control bones
1 chain of deformation bones
2 chains of mechanical bones: Spring bone source and target

The control bones allow for manual animation,
The spring bones take care of the spring constraint mechanism,
The deformation bones copy either the control or the spring bones.
"""

import bpy
from bpy.props import *
from rna_prop_ui import rna_idprop_ui_prop_get
import math
from mathutils import Matrix
from ..utils import connected_children_names
from ..utils import MetarigError
from ..utils import copy_bone
from ..utils import strip_org, make_mechanism_name, make_deformer_name
from ..utils import create_bone_widget


def gen_tabs(depth):
    return " " * 4 * depth


def get_spring_prop_str(data_path, indent=1, escape=False):
    """ Expose generic spring constraint props, provided """
    expose_spring_props = """
{indent}layout.prop({data_path}, '{l}speed{r}', text="Speed")
{indent}layout.prop({data_path}, '{l}damping{r}', text="Damping")
{indent}layout.prop({data_path}, '{l}gravity{r}', text="Gravity")
{indent}layout.prop({data_path}, '{l}stiffness_x{r}', text="Stiffness X")
{indent}layout.prop({data_path}, '{l}stiffness_y{r}', text="Stiffness Y")
{indent}layout.prop({data_path}, '{l}stiffness_z{r}', text="Stiffness Z")
{indent}layout.prop({data_path}, '{l}dist_threshold{r}', text="Distance threshold")
{indent}layout.prop({data_path}, '{l}fast_factor{r}', text="Fast factor")
{indent}layout.prop({data_path}, '{l}reset_on_frame{r}', text="Reset on frame")
"""
    return expose_spring_props.format(
        data_path=data_path,
        indent=gen_tabs(1),
        l='["' if escape else "",
        r='"]' if escape else ""
    )


def get_props_display(individual, indent=1):
    indi = """
{indent}for b in control_bones + preview_bones:
{indent}if is_selected([b, ]):
{indent}    spring = lookup[b]
{indent}    name = spring[len("MCH-"):-len("_target")]
{indent}    layout.label(text="Spring properties for '%s'" % name)
{indent}    {props}
"""

    shared = """
{indent}{props}
{indent}for b in control_bones + preview_bones:
{indent}    if is_selected([b, ]):
{indent}        spring = lookup[b]
{indent}        name = spring[len("MCH-"):-len("_target")]
{indent}        layout.label(text="Spring properties for '%s'" % name)
{indent}        layout.prop(pose_bones[spring], '["speed_factor"]', text="Speed factor")
{indent}        layout.prop(pose_bones[spring], '["gravity_factor"]', text="Gravity factor")
{indent}        layout.prop(pose_bones[spring], '["damping_factor"]', text="Damping factor")
"""

    if individual:
        return indi.format(
            indent=gen_tabs(indent),
            props=get_spring_prop_str(
                "pose_bones[spring].constraints[\"Spring\"i]",
                indent=indent + 1,
                escape=False
            )
        )
    else:
        return shared.format(
            indent=gen_tabs(indent),
            props=get_spring_prop_str(
                "pose_bones[prop_bone]",
                indent=indent + 1,
                escape=True
            )
        )


def get_main_script(individual, prop_bone, lookup, control_bones,
                    preview_bones, spring_bones
                    ):
    main_script = """
prop_bone = "{prop_bone}"
lookup = {lookup}
control_bones = {control_bones}
preview_bones = {preview_bones}
spring_bones = {spring_bones}

if is_selected(control_bones + preview_bones):
    layout.prop(pose_bones[prop_bone], '["follow_spring"]', text="Follow spring")
    {properties_display}
"""
    disp = get_props_display(individual, indent=1)
    return main_script.format(
        prop_bone=prop_bone,
        lookup=lookup,
        control_bones=control_bones,
        preview_bones=preview_bones,
        spring_bones=spring_bones,
        properties_display=disp
    )


class Rig:
    def __init__(self, obj, bone, params):
        self.obj = obj
        self.org_bones = [bone] + connected_children_names(obj, bone)
        self.params = params

        if len(self.org_bones) < 3:
            raise MetarigError("Need at least three bones for Spring-chain")

        bpy.ops.object.mode_set(mode='EDIT')
        self.original_parent = self.obj.data.edit_bones[bone].parent.name
        bpy.ops.object.mode_set(mode='OBJECT')

    def generate(self):
        #----------------------------------------------------------------------
        # Create duplicates
        #----------------------------------------------------------------------
        bpy.ops.object.mode_set(mode='EDIT')

        # Create deform bones
        self.deform_bones = [
            copy_bone(self.obj, bone, make_deformer_name(strip_org(bone)))
            for bone in self.org_bones
        ]

        # Create mch chain 1: Spring bone source
        self.mch_source = [
            copy_bone(self.obj, bone,
                      make_mechanism_name(strip_org(bone) + "_source")
                      )
            for bone in self.org_bones
        ]

        # Create mch chain 2: Spring bone target
        self.mch_target = [
            copy_bone(self.obj, bone,
            make_mechanism_name(strip_org(bone) + "_target"))
            for bone in self.org_bones
        ]

        # Create control bones
        self.control_bones = [
                copy_bone(self.obj, bone, strip_org(bone))
                for bone in self.org_bones
        ]

        # Create spring preview bones
        self.preview_bones = [
                copy_bone(self.obj, bone, strip_org(bone) + "_preview")
                for bone in self.org_bones
        ]

        #----------------------------------------------------------------------
        # Parenting/parent
        #----------------------------------------------------------------------
        def parent(childName, parentName, keep_offset):
            bpy.ops.armature.select_all(action='DESELECT')
            edit_bones = self.obj.data.edit_bones
            edit_bones[childName].select = True
            edit_bones[parentName].select = True
            edit_bones.active = edit_bones[parentName]
            bpy.ops.armature.parent_set(
                    type='OFFSET' if keep_offset else 'CONNECTED'
                    )

        # Ensure control bone parent integrity
        lastName = None
        for bName in self.control_bones:
            if lastName:
                parent(bName, lastName, False)
            else:
                edit_bones = self.obj.data.edit_bones
                edit_bones[bName].parent = edit_bones[self.original_parent]
            lastName = bName

        # Deform and preview bones need no parents
        for bName in self.deform_bones + self.preview_bones:
            self.obj.data.edit_bones[bName].parent = None

        # Cross-parent source and target spring bones
        tot = len(self.mch_source)
        for i, (sourceName, targetName) in \
                enumerate(zip(self.mch_source, self.mch_target)):
            parent(targetName, sourceName, True)
            if i < tot - 1:
                parent(
                    self.obj.data.edit_bones[self.mch_source[i + 1]].name,
                    targetName, True
                )

        #----------------------------------------------------------------------
        # Align Bone Roll
        #----------------------------------------------------------------------
        for target_list in [self.control_bones, self.deform_bones,
                            self.mch_source, self.mch_target,
                            self.preview_bones]:
            for orgName, targetName in zip(self.org_bones, target_list):
                align_bone_roll(self.obj, targetName, orgName)

        #----------------------------------------------------------------------
        # Create widgets
        #----------------------------------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')
        for b in self.preview_bones:
            create_bone_widget(self.obj, b)
            self.obj.pose.bones[b].bone.hide_select = True

        #----------------------------------------------------------------------
        # Transform locks
        #----------------------------------------------------------------------
        for b in self.preview_bones:
            self.obj.pose.bones[b].lock_rotation[0] = True
            self.obj.pose.bones[b].lock_rotation[1] = True
            self.obj.pose.bones[b].lock_rotation[2] = True

            self.obj.pose.bones[b].lock_rotations_4d = True
            self.obj.pose.bones[b].lock_rotation_w = True

            self.obj.pose.bones[b].lock_location[0] = True
            self.obj.pose.bones[b].lock_location[1] = True
            self.obj.pose.bones[b].lock_location[2] = True

            self.obj.pose.bones[b].lock_scale[0] = True
            self.obj.pose.bones[b].lock_scale[1] = True
            self.obj.pose.bones[b].lock_scale[2] = True

        #----------------------------------------------------------------------
        # Properties
        #----------------------------------------------------------------------
        propBoneName = self.org_bones[0]
        propPb = self.obj.pose.bones[propBoneName]

        # Follow spring
        prop = rna_idprop_ui_prop_get(propPb, "follow_spring", create=True)
        propPb["follow_spring"] = 1.0
        prop["soft_min"] = prop["min"] = 0.0
        prop["soft_max"] = prop["max"] = 1.0

        # If using "shared properties", create a proxy for each property
        # TODO: implement non-float props
        # Fomat: [Name, min, max, default]
        if self.params.unify_spring_props:
            props = [
                    ["speed",           0,  100,    1.0],
                    ["damping",         0,  1.0,    0.5],
                    ["gravity",         0,  100,    0.0],
                    ["stiffness_x",     0,  1.0,    0.0],
                    ["stiffness_y",     0,  1.0,    0.0],
                    ["stiffness_z",     0,  1.0,    0.0],
                    ["dist_threshold",  0,   10,    1.0],
                    ["fast_factor",     0,   10,    3.0],
                    # Hacky:
                    ["reset_on_frame", -99000, 99000, 1],
                    ]
            for name, mini, maxi, default in props:
                prop = rna_idprop_ui_prop_get(propPb, name, create=True)
                propPb[name] = default
                prop["soft_min"] = prop["min"] = mini
                prop["soft_max"] = prop["max"] = maxi

        #----------------------------------------------------------------------
        # Constraining
        #----------------------------------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')

        # Create Spring constraints
        propPb = self.obj.pose.bones[propBoneName]
        for sourceName, targetName in zip(self.mch_source, self.mch_target):
            factorPb = self.obj.pose.bones[targetName]

            con = self.obj.pose.bones[targetName].constraints.new('SPRING')
            con.target = self.obj
            con.subtarget = sourceName

            # If "shared propreties" are enabled,
            # create a factor property for ey
            if self.params.unify_spring_props:
                tweakable_props = [
                    "speed",
                    "gravity",
                    "damping"
                ]

                for n in tweakable_props:
                    prop_name = "%s_factor" % n
                    prop = rna_idprop_ui_prop_get(
                            factorPb, prop_name, create=True
                            )
                    factorPb[prop_name] = 1
                    prop["soft_min"] = prop["min"] = 0
                    prop["soft_max"] = prop["max"] = 100
                    print(prop)

                for name, mini, maxi, default in props:
                    fcurve = con.driver_add(name)
                    driver = fcurve.driver

                    driver.type = 'SCRIPTED'
                    if name in tweakable_props:
                        driver.expression = 'var * factor'
                    else:
                        driver.expression = 'var'

                    # Prop bone dictates
                    var1 = driver.variables.new()
                    var1.name = 'var'
                    var1.targets[0].id_type = 'OBJECT'
                    var1.targets[0].id = self.obj
                    data_path = propPb.path_from_id() + '["%s"]' % name
                    var1.targets[0].data_path = data_path

                    if name in tweakable_props:
                        # Fallof factor
                        var2 = driver.variables.new()
                        var2.name = 'factor'
                        var2.targets[0].id_type = 'OBJECT'
                        var2.targets[0].id = self.obj
                        prop_path = '["%s_factor"]' % name
                        data_path = factorPb.path_from_id() + prop_path
                        var2.targets[0].data_path = data_path

        # Create Spring control constraints
        for sourceName, ctrlName in zip(self.mch_source, self.control_bones):
            con = self.obj.pose.bones[sourceName].constraints.new(
                    'COPY_ROTATION'
                    )
            con.target = self.obj
            con.subtarget = ctrlName
            con.target_space = 'LOCAL'
            con.owner_space = 'LOCAL'

        # Constrain deformation bones
        for defName, springName, ctrlName in zip(
                self.deform_bones, self.mch_target, self.control_bones
        ):
            # Follow manual control
            con = self.obj.pose.bones[defName].constraints.new(
                    'COPY_TRANSFORMS')
            con.name = "Follow Manual"
            con.target = self.obj
            con.subtarget = ctrlName

            # Follow Spring
            con = self.obj.pose.bones[defName].constraints.new(
                    'COPY_TRANSFORMS')
            con.name = "Follow Spring"
            con.target = self.obj
            con.subtarget = springName
            driver = con.driver_add("influence").driver
            var = driver.variables.new()
            var.name = "follow_spring"
            var.targets[0].id_type = 'OBJECT'
            var.targets[0].id = self.obj
            data_path = propPb.path_from_id() + '["follow_spring"]'
            var.targets[0].data_path = data_path
            driver.type = 'SCRIPTED'
            driver.expression = "follow_spring"

        # Constrain preview bones
        for deformName, previewName in zip(
                self.deform_bones, self.preview_bones
        ):
            con = self.obj.pose.bones[previewName].constraints.new(
                    'COPY_TRANSFORMS'
            )
            con.name = "Follow Manual"
            con.target = self.obj
            con.subtarget = deformName

        # Create a lookup table for exposing spring settings
        lookup = {}
        for l in [self.control_bones, self.preview_bones, ]:
            for key, value in zip(l, self.mch_target):
                lookup[key] = value

        out = get_main_script(
            not self.params.unify_spring_props,
            propBoneName,
            lookup,
            self.control_bones,
            self.preview_bones,
            self.mch_target
        )
        return [out, ]


def add_parameters(params):
    params.unify_spring_props = BoolProperty(
            name="Unify spring properties", default=True,
            description="Instead of exposing each spring bone's poperties, "
                    "expose one set for all")


def parameters_ui(layout, params):
    r = layout.row()
    r.prop(params, "unify_spring_props")

# This is copied from old rigify since it has been removed since...
def align_bone_roll(obj, bone1, bone2):
    """ Aligns the roll of two bones.  """

    bone1_e = obj.data.edit_bones[bone1]
    bone2_e = obj.data.edit_bones[bone2]
    
    bone1_e.roll = 0.0
    
    # Get the directions the bones are pointing in, as vectors
    y1 = bone1_e.y_axis
    x1 = bone1_e.x_axis
    y2 = bone2_e.y_axis
    x2 = bone2_e.x_axis
    
    # Get the shortest axis to rotate bone1 on to point in the same direction as bone2
    axis = y1.cross(y2)
    axis.normalize()
    
    # Angle to rotate on that shortest axis
    angle = y1.angle(y2)
    
    # Create rotation matrix to make bone1 point in the same direction as bone2
    rot_mat = Matrix.Rotation(angle, 3, axis)
    
    # Roll factor
    x3 = rot_mat * x1
    dot = x2 * x3
    if dot > 1.0:
        dot = 1.0
    elif dot < -1.0:
        dot = -1.0
    roll = math.acos(dot)
    
    # Set the roll
    bone1_e.roll = roll
    
    # Check if we rolled in the right direction
    x3 = rot_mat * bone1_e.x_axis
    check = x2 * x3
    
    # If not, reverse
    if check < 0.9999:
        bone1_e.roll = -roll
