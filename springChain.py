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

from rna_prop_ui import rna_idprop_ui_prop_get

from ..utils import connected_children_names
from ..utils import MetarigError
from ..utils import copy_bone
from ..utils import strip_org, make_mechanism_name, make_deformer_name
from ..utils import create_circle_widget, create_bone_widget
from ..utils import align_bone_roll

script = """
prop_bone = "{prop_bone}"
lookup = {lookup}
control_bones = {control_bones}
preview_bones = {preview_bones}
spring_bones = {spring_bones}

if is_selected(control_bones + preview_bones):
    layout.prop(pose_bones[prop_bone], '["follow_spring"]', text="Follow spring")
    
    # Display Spring properties
    for b in control_bones + preview_bones:
        if is_selected([b, ]):
            spring = lookup[b]
            name = spring[len("MCH-"):-len("_target")]
            layout.label(text="Spring properties for '%s'" % name)
            layout.prop(pose_bones[spring].constraints["Spring"], 'speed')
            layout.prop(pose_bones[spring].constraints["Spring"], 'damping')
            layout.prop(pose_bones[spring].constraints["Spring"], 'gravity')
            layout.prop(pose_bones[spring].constraints["Spring"], 'stiffness_x')
            layout.prop(pose_bones[spring].constraints["Spring"], 'stiffness_y')
            layout.prop(pose_bones[spring].constraints["Spring"], 'stiffness_z')
            layout.prop(pose_bones[spring].constraints["Spring"], 'dist_threshold')
            layout.prop(pose_bones[spring].constraints["Spring"], 'fast_factor')
            layout.prop(pose_bones[spring].constraints["Spring"], 'reset_on_frame')
"""


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
        #---------------------------------------------------------------------------------------------------------------
        # Create duplicates
        #---------------------------------------------------------------------------------------------------------------
        bpy.ops.object.mode_set(mode='EDIT')

        # Create deform bones
        self.deform_bones = [copy_bone(self.obj, bone, make_deformer_name(strip_org(bone))) for bone in self.org_bones]

        # Create mch chain 1: Spring bone source
        self.mch_source = [
            copy_bone(self.obj, bone, make_mechanism_name(strip_org(bone) + "_source")) for bone in self.org_bones
        ]

        # Create mch chain 2: Spring bone target
        self.mch_target = [
            copy_bone(self.obj, bone, make_mechanism_name(strip_org(bone) + "_target")) for bone in self.org_bones
        ]

        # Create control bones
        self.control_bones = [copy_bone(self.obj, bone, strip_org(bone)) for bone in self.org_bones]

        # Create spring preview bones
        self.preview_bones = [copy_bone(self.obj, bone, strip_org(bone) + "_preview") for bone in self.org_bones]

        #---------------------------------------------------------------------------------------------------------------
        # Parenting/parent
        #---------------------------------------------------------------------------------------------------------------
        def parent(childName, parentName, keep_offset):
            bpy.ops.armature.select_all(action='DESELECT')
            self.obj.data.edit_bones[childName].select = True
            self.obj.data.edit_bones[parentName].select = True
            self.obj.data.edit_bones.active = self.obj.data.edit_bones[parentName]
            bpy.ops.armature.parent_set(type='OFFSET' if keep_offset else 'CONNECTED')

        # Ensure control bone parent integrity
        lastName = None
        for bName in self.control_bones:
            if lastName:
                parent(bName, lastName, False)
            else:
                self.obj.data.edit_bones[bName].parent = self.obj.data.edit_bones[self.original_parent]
            lastName = bName

        # Deform and preview bones need no parents
        for bName in self.deform_bones + self.preview_bones:
            self.obj.data.edit_bones[bName].parent = None

        # Cross-parent source and target spring bones
        tot = len(self.mch_source)
        for i, (sourceName, targetName) in enumerate(zip(self.mch_source, self.mch_target)):
            parent(targetName, sourceName, True)
            if i < tot - 1:
                parent(
                    self.obj.data.edit_bones[self.mch_source[i + 1]].name,
                    targetName, True
                )

        #---------------------------------------------------------------------------------------------------------------
        # Align Bone Roll
        #---------------------------------------------------------------------------------------------------------------
        for target_list in [self.control_bones, self.deform_bones, self.mch_source,
                            self.mch_target, self.preview_bones]:
            for orgName, targetName in zip(self.org_bones, target_list):
                align_bone_roll(self.obj, targetName, orgName)

        #---------------------------------------------------------------------------------------------------------------
        # Create widgets
        #---------------------------------------------------------------------------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')
        for b in self.preview_bones:
            create_bone_widget(self.obj, b)

        #---------------------------------------------------------------------------------------------------------------
        # Transform locks
        #---------------------------------------------------------------------------------------------------------------
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
        
        #---------------------------------------------------------------------------------------------------------------
        # Properties
        #---------------------------------------------------------------------------------------------------------------
        propBoneName = self.org_bones[0]
        propPb = self.obj.pose.bones[propBoneName]

        # Follow spring
        prop = rna_idprop_ui_prop_get(propPb, "follow_spring", create=True)
        propPb["follow_spring"] = 1.0
        prop["soft_min"] = prop["min"] = 0.0
        prop["soft_max"] = prop["max"] = 1.0

        #---------------------------------------------------------------------------------------------------------------
        # Constraining
        #---------------------------------------------------------------------------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')

        # Create Spring constraints
        for sourceName, targetName in zip(self.mch_source, self.mch_target):
            con = self.obj.pose.bones[targetName].constraints.new('SPRING')
            con.target = self.obj
            con.subtarget = sourceName

        # Create Spring control constraints
        for sourceName, ctrlName in zip(self.mch_source, self.control_bones):
            con = self.obj.pose.bones[sourceName].constraints.new('COPY_ROTATION')
            con.target = self.obj
            con.subtarget = ctrlName
            con.target_space = 'LOCAL'
            con.owner_space = 'LOCAL'

        # Constrain deformation bones
        for defName, springName, ctrlName in zip(self.deform_bones, self.mch_target, self.control_bones):
            # Follow Spring
            con = self.obj.pose.bones[defName].constraints.new('COPY_TRANSFORMS')
            con.name = "Follow Spring"
            con.target = self.obj
            con.subtarget = springName
            driver = con.driver_add("influence").driver
            var = driver.variables.new()
            var.name = "follow_spring"
            var.targets[0].id_type = 'OBJECT'
            var.targets[0].id = self.obj
            var.targets[0].data_path = propPb.path_from_id() + '["follow_spring"]'
            driver.type = 'SCRIPTED'
            driver.expression = "follow_spring"

            # Follow manual control
            con = self.obj.pose.bones[defName].constraints.new('COPY_TRANSFORMS')
            con.name = "Follow Manual"
            con.target = self.obj
            con.subtarget = ctrlName
            driver = con.driver_add("influence").driver
            var = driver.variables.new()
            var.name = "follow_spring"
            var.targets[0].id_type = 'OBJECT'
            var.targets[0].id = self.obj
            var.targets[0].data_path = propPb.path_from_id() + '["follow_spring"]'
            driver.type = 'SCRIPTED'
            driver.expression = "1 - follow_spring"

        # Constrain preview bones
        for springName, previewName in zip(self.mch_target, self.preview_bones):
            con = self.obj.pose.bones[previewName].constraints.new('COPY_TRANSFORMS')
            con.name = "Follow Manual"
            con.target = self.obj
            con.subtarget = springName

        # Create a lookup table for exposing spring settings
        lookup = {}
        for l in [self.control_bones, self.preview_bones, ]:
            for key, value in zip(l, self.mch_target):
                lookup[key] = value

        out = script.format(
            prop_bone=propBoneName,
            lookup=lookup,
            control_bones=self.control_bones,
            preview_bones=self.preview_bones,
            spring_bones=self.mch_target
        )
        return [out, ]
