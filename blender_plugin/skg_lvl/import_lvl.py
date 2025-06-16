import pathlib
from .Reader import *  # struct + os
from .SimpleParse import *

import bpy, math
import mathutils
import bmesh
from mathutils import Vector, Matrix


def load_lvl(file_path):
    print("Starting to load level")
    scene = bpy.context.scene

    # Используем bpy.path для работы с путями
    file_path = bpy.path.abspath(file_path)
    texture_directory = bpy.path.abspath(os.path.join(os.path.dirname(file_path), 'textures'))
    file_basename = os.path.splitext(os.path.basename(file_path))[0]
    print("Texture_directory: " + texture_directory)

    if not pathlib.Path(bpy.path.abspath(os.path.join(os.path.dirname(file_path), file_basename, 'background.sgi.msb'))).exists():
        raise FileNotFoundError("Missing background.sgi.msb in subfolder (don't use background.lvl)")

    with open(file_path, "r", encoding='ascii') as f:
        content = f.readlines()

    # Note for Pointlight: Last two params are "Radius in pixels(at default screen res of 1280x720)" and nevercull
    # 4 point lights are used for effects
    # Default values: (thanks MikeZ)
    # stageSizeDefaultX = 3750
    # stageSizeDefaultY = 2000
    # defaultShadowDistance = -400 # negative is down (below the chars), positive is up (on floor behind them)
    # Guessed default values:
    # z near and far: 3,20000
    parser_instructions = [['StageSize:', 'ii'],
                           ['BottomClearance:', 'i'],
                           ['Start1:', 'i'],
                           ['Start2:', 'i'],
                           ['ShadowDir:', 'c'],  # deprecated, only U and D are allowed characters
                           ['ShadowDist:', 'i'],  # Use this instead (to convert: Default is -400)
                           ['Light:', 'siiifffis'],  # String is 'Pt',  rgbxyz...  , 8 allowed (use max 4)
                           ['Light:', 'siiifffi'],  # Pointlight without nevercull
                           ['Light:', 'siiifff'],  # String is 'Dir', rgbxyz,  4 allowed (use max 2)
                           ['Light:', 'siii'],  # String is 'Amb', rgb,     1 allowed
                           ['CAMERA', 'iii'],  # fov, znear zfar
                           ['CAMERA', 'i'],  # fov
                           ['3D', 'fii'],  # tile_rate, tilt_height1, tilt_height2
                           ['2D', 's'],  # Contains the path to the texture for the 2D level
                           ['Music_Intro', 's'],
                           ['Music_Loop', 's'],
                           ['Music_InterruptIntro', 'i'],  # If >0 loop starts even if intro hasn't finished
                           ['Music_Outro', 's'],
                           ['Replace', 'sssss'],
                           ['ForceReplace', 'i'],
                           ['ReplaceNumIfChar', 'si'],
                           ['Replace', 'ss']]  # This one is for ReplaceNumIfChar
    print("LVL data is read but not used for now")
    lvl_metadata = parse(content, parser_instructions)
    sgi = SGI(os.path.join(os.path.dirname(file_path), file_basename, 'background.sgi.msb'))
    sgi_data = sgi.get_metadata()

    sgm_data = []  # List of models

    # SGM
    print("Starting SGM import")
    print("===================")
    n_of_vertices = 0
    for element in sgi_data:
        print("Current sgm file: " + element['shape_name'] + '.sgm.msb')

        sgm = SGM(os.path.join(os.path.abspath(os.path.dirname(file_path)), file_basename,
                               element['shape_name'] + '.sgm.msb'))
        current_sgm = sgm.get_data()
        sgm_data.append(current_sgm)

        # Check if the model has any joint data, if it has load the sgs file
        # Not working correctly

        sgs_data = None
        if current_sgm['attribute_length_per_vertex'] == 44:
            sgs = SGS(os.path.join(os.path.abspath(os.path.dirname(file_path)), file_basename,
                                   element['shape_name'] + "." + SGS.FILE_EXTENSION))
            sgs_data = sgs.get_data()

        vertex_list = []
        normals = []
        uv_coords = []
        vertex_colors = []
        # Optional data
        joint_ids = []
        joint_weights = []
        for vertex in current_sgm['vertices']:
            x = struct.unpack('>f', vertex[0:4])[0]
            y = struct.unpack('>f', vertex[4:8])[0]
            z = struct.unpack('>f', vertex[8:12])[0]
            vertex_list.append(mathutils.Vector((x, y, z)))
            # Normals
            normal_x = struct.unpack('>f', vertex[12:16])[0]
            normal_y = struct.unpack('>f', vertex[16:20])[0]
            normal_z = struct.unpack('>f', vertex[20:24])[0]
            normals.append([normal_x, normal_y, normal_z])
            # UV coordinates
            u = struct.unpack('>f', vertex[24:28])[0]
            v = struct.unpack('>f', vertex[28:32])[0]
            uv_coords.append([u, v])
            # UCHAR4 ==> unsigned char x,y,z,w ==> Assuming rgba? TODO correct?
            r = struct.unpack('>B', vertex[32:33])[0]
            g = struct.unpack('>B', vertex[33:34])[0]
            b = struct.unpack('>B', vertex[34:35])[0]
            a = struct.unpack('>B', vertex[35:36])[0]
            # Blender wants the vertex color channels to be between 0 and 1
            vertex_colors.append([r / 255.0, g / 255.0, b / 255.0, a / 255.0])
            # Check if we have bone data
            if len(vertex) == 44:
                # bone id 0 = no bone, so first bone is 1
                joint_ids.append(struct.unpack('BBBB', vertex[36:40]))
                temp_joint_weights = struct.unpack('BBBB', vertex[40:44])
                # Normalize them from 0 .. 255 to 0.0 to 1.0
                joint_weights.append([temp_joint_weights[0]/255.0, temp_joint_weights[1]/255.0,
                                      temp_joint_weights[2]/255.0, temp_joint_weights[3]/255.0])
        n_of_vertices += len(vertex_list)
        mesh = bpy.data.meshes.new(element['shape_name'])
        # Edges are calculated by blender (see source for from_pydata)
        mesh.from_pydata(vertex_list, [], current_sgm['index_buffer'])

        # In Blender 4.4, object selection is different
        # Deselect all objects
        for o in bpy.context.selected_objects:
            o.select_set(False)

        mesh.update()
        mesh.validate()

        # bmesh operations for UV only
        bmesh_mesh = bmesh.new()
        bmesh_mesh.from_mesh(mesh)

        # UV handling in newer Blender versions
        try:
            uv_layer = bmesh_mesh.loops.layers.uv.new("UVMap")
            
            # Set UV coordinates using bmesh
            for face_idx, face in enumerate(bmesh_mesh.faces):
                for loop_idx, loop in enumerate(face.loops):
                    vertex_idx = current_sgm['index_buffer'][face_idx][loop_idx]
                    loop[uv_layer].uv = uv_coords[vertex_idx]
        
            # Apply bmesh changes back to the mesh
            bmesh_mesh.to_mesh(mesh)
        except Exception as e:
            print(f"Warning: Error setting UV coordinates: {str(e)}")
        finally:
            bmesh_mesh.free()
            
        # Создаем атрибут цвета для вершин
        color_attr = mesh.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
        
        # Устанавливаем цвета для каждого угла полигона
        for face_idx, face in enumerate(mesh.polygons):
            for loop_idx, loop in enumerate(face.loop_indices):
                vertex_idx = current_sgm['index_buffer'][face_idx][loop_idx]
                color_attr.data[loop].color = vertex_colors[vertex_idx]
        
        # Обновляем меш
        mesh.update()

        # Create new object from mesh
        new_object = bpy.data.objects.new(element['element_name'], mesh)

        # This sets position, rotation and scale
        new_object.matrix_world = mathutils.Matrix(element['mat4'])

        # Get material and assign it to object
        current_material = get_material(texture_directory, current_sgm['texture_name'])
        new_object.data.materials.append(current_material)

        # Link object to collection
        bpy.context.collection.objects.link(new_object)
        
        # Select the new object
        new_object.select_set(True)
        
        # Make it the active object
        if bpy.context.object is None or bpy.context.object.mode == 'OBJECT':
            bpy.context.view_layer.objects.active = new_object
            
        # Visibility in Blender 4.4
        if element['is_visible'] == 0:
            new_object.hide_viewport = True
            new_object.hide_render = True

        # Now that the basic geometry is set up we add bone info if there is any
        if sgs_data is not None:
            # Armature creation in Blender 4.4 is different
            # This would need more extensive rewriting
            pass

        # Create vertex groups for joints if we have data
        if len(joint_ids) > 0 and len(joint_weights) > 0:
            # This would need to be updated for Blender 4.4's weight painting system
            pass

    print("Stage has " + str(len(sgi_data)) + " objects")
    print("Stage has " + str(n_of_vertices) + " vertices")


def get_material(path, name):
    # Check if material already exists
    # If yes: Return the old one, else make new
    try:
        return bpy.data.materials[name]
    except KeyError:  # Not found # TODO error handling!
        print("Material " + name + " not found, making a new one")
    
    # Load image (you are expected to have stages-textures.gfs extracted)
    # texture_path = os.path.normpath(os.path.join(path, os.pardir, os.pardir, os.pardir,
    #                                              'stages-textures', 'stages', 'textures', name + '.dds'))
    texture_candidates = [
    os.path.normpath(os.path.join(path, os.pardir, os.pardir, os.pardir,
                 'stages-textures', 'stages', 'textures', name + '.dds')),
    os.path.normpath(os.path.join(path, os.pardir, os.pardir, os.pardir, os.pardir,
                                  'levels-textures', 'temp', 'levels', 'textures', name + '.dds')),
    os.path.normpath(os.path.join(path, os.pardir, os.pardir, os.pardir, os.pardir,
                                  'levels', 'temp', 'levels', 'textures', name + '.dds'))
    ]

    # Ищем первый существующий файл
    found_texture_path = None
    for candidate in texture_candidates:
        if os.path.isfile(candidate):
            found_texture_path = candidate
            break
    
    # Используем найденный путь или оригинальный, если ничего не найдено
    texture_path = found_texture_path if found_texture_path else texture_candidates[0]

    try:
        # Используем безопасную загрузку изображения
        image = None
        if os.path.exists(texture_path):
            image = bpy.data.images.load(texture_path)
        else:
            # Если текстура не найдена, создаем заполнитель
            print(f"Warning: Texture not found at {texture_path}, using placeholder")
            image = bpy.data.images.new(name=name, width=1024, height=1024)
            image.generated_color = (1, 0, 1, 1)  # Розовый цвет как индикатор отсутствия текстуры
    except Exception as e:
        print(f"Error loading texture: {str(e)}")
        # Создаем заполнитель в случае ошибки
        image = bpy.data.images.new(name=name, width=1024, height=1024)
        image.generated_color = (1, 0, 1, 1)
        
    # Create material with modern Blender nodes
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    
    # Clear default nodes
    nodes = mat.node_tree.nodes
    nodes.clear()
    
    # Create texture image node
    tex_node = nodes.new('ShaderNodeTexImage')
    tex_node.image = image
    tex_node.location = (-300, 0)
    
    # Set image sampling
    tex_node.interpolation = 'Closest'  # No interpolation - box filter equivalent
    
    # Create principled BSDF shader
    bsdf_node = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf_node.location = (0, 0)
    
    # For shadeless appearance (like the original)
    bsdf_node.inputs['Specular IOR Level'].default_value = 0.0
    bsdf_node.inputs['Roughness'].default_value = 1.0
    bsdf_node.inputs['Sheen Tint'].default_value = (0.0, 0.0, 0.0, 1.0)
        
    # Connect texture to shader
    links = mat.node_tree.links
    links.new(tex_node.outputs['Color'], bsdf_node.inputs['Base Color'])
    links.new(tex_node.outputs['Alpha'], bsdf_node.inputs['Alpha'])
    
    # Create output node
    output_node = nodes.new('ShaderNodeOutputMaterial')
    output_node.location = (300, 0)
    
    # Connect shader to output
    links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])
    
    # Set material properties
    mat.blend_method = 'HASHED'  # For transparency
    if hasattr(mat, 'shadow_method'):  # Проверяем, есть ли этот атрибут в Blender 4.4
        mat.shadow_method = 'NONE'  # No shadows
    
    return mat


def load(operator, context, filepath=""):
    try:
        # Преобразуем путь в абсолютный и нормализуем его
        filepath = bpy.path.abspath(filepath)
        load_lvl(filepath)
        return {'FINISHED'}
    except Exception as e:
        operator.report({'ERROR'}, f"Error loading file: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'CANCELLED'}


class SGS(Reader):
    FILE_EXTENSION = "sgs.msb"
    FILE_VERSION = "2.0"

    def __init__(self, file_path):
        # Используем bpy.path.abspath вместо os.path.abspath
        file_path = bpy.path.abspath(file_path)
        super().__init__(open(file_path, "rb"), os.path.getsize(file_path), BIG_ENDIAN)
        self.file_path = file_path

    def get_data(self):
        sgs_data = {'names': [], 'parent_id': [], 'bone_mat': []}
        if self.read_pascal_string() != SGS.FILE_VERSION:
            raise ValueError("Invalid version")
        number_of_joints = self.read_int(8)
        for _ in range(0, number_of_joints):
            sgs_data['names'].append(self.read_pascal_string())
            sgs_data['parent_id'].append(self.read_int(4, is_signed=True))
            bone_mat = self.read_mat4()
            sgs_data['bone_mat'].append(bone_mat)
        return sgs_data

    def read_pascal_string(self):
        """
        Read long+ASCII String from internal file
        :return: String
        """
        return self.read_string(self.read_int(8))

    def read_mat4(self):
        mat = [self.read_float() for _ in range(0, 16)]
        # Column major, apparently
        return [[mat[0], mat[4], mat[8], mat[12]],
                [mat[1], mat[5], mat[9], mat[13]],
                [mat[2], mat[6], mat[10], mat[14]],
                [mat[3], mat[7], mat[11], mat[15]]]


class SGA(Reader):
    FILE_EXTENSION = "sga.msb"
    FILE_VERSION = "3.0"

    def __init__(self, file_path):
        super().__init__(open(file_path, "rb"), os.path.getsize(file_path), BIG_ENDIAN)
        self.file_path = os.path.abspath(file_path)

    def get_data(self):
        sga_data = {}
        if self.read_pascal_string() != SGA.FILE_VERSION:
            raise ValueError("Invalid version")
        unknown = self.read_int(4)
        n_of_elements = self.read_int(8)
        n_of_uv_tracks = self.read_int(8)
        anim_length_sec = self.read_float()

        return sga_data

    def read_pascal_string(self):
        """
        Read long+ASCII String from internal file
        :return: String
        """
        return self.read_string(self.read_int(8))

    def read_mat4(self):
        return [self.read_float() for _ in range(0, 16)]


class SGM(Reader):
    FILE_EXTENSION = "sgm.msb"
    FILE_VERSION = "2.0"

    def __init__(self, file_path):
        super().__init__(open(file_path, "rb"), os.path.getsize(file_path), BIG_ENDIAN)
        self.file_path = os.path.abspath(file_path)

    def get_data(self):
        sgm_data = {}
        if self.read_pascal_string() != SGM.FILE_VERSION:
            raise ValueError("Invalid version")
        sgm_data['texture_name'] = self.read_pascal_string()
        self.skip_bytes(52)  # TODO Unknown stuff
        sgm_data['data_format'] = self.read_pascal_string()
        sgm_data['attribute_length_per_vertex'] = self.read_int(8)
        number_of_vertices = self.read_int(8)
        number_of_triangles = self.read_int(8)
        number_of_joints = self.read_int(8)
        print("Vertices: " + str(number_of_vertices))
        print("Triangles: " + str(number_of_triangles))
        print("Joints: " + str(number_of_joints))
        # VERTICES
        vertices = []
        for _ in range(0, number_of_vertices):
            vertices.append(self.file.read(sgm_data['attribute_length_per_vertex']))
        sgm_data['vertices'] = vertices
        # TRIANGLES for an index buffer
        triangles = []
        for _ in range(0, number_of_triangles):
            triangles.append([self.read_int(2), self.read_int(2), self.read_int(2)])
        sgm_data['index_buffer'] = triangles

        # Bounding box, we don't need it for Blender, skipping it
        # Is regenerated during export anyway
        # Skip 6*4 bytes = 24 bytes
        self.skip_bytes(24)
        # Skeleton info
        joints = []
        for _ in range(0, number_of_joints):
            joints.append([self.read_pascal_string()])
        for i in range(0, number_of_joints):
            joints[i].append(self.read_mat4())
        sgm_data['joints'] = joints
        return sgm_data

    def read_pascal_string(self):
        """
        Read long+ASCII String from internal file
        :return: String
        """
        return self.read_string(self.read_int(8))

    def read_mat4(self):
        return [self.read_float() for _ in range(0, 16)]


class SGI(Reader):
    FILE_EXTENSION = "sgi.msb"
    FILE_VERSION = "2.0"

    def __init__(self, file_path):
        super().__init__(open(file_path, "rb"), os.path.getsize(file_path), BIG_ENDIAN)
        self.file_path = os.path.abspath(file_path)

    def get_metadata(self):
        """
        Read SGI file
        :raise ValueError: File integrity compromised
        """
        sgi_data = []

        if self.read_pascal_string() != SGI.FILE_VERSION:
            raise ValueError("Invalid version")
        number_of_elements = self.read_int(8)

        print("Reading SGI file (" + str(number_of_elements) + " elements)")
        print("==================================")

        for _ in range(0, number_of_elements):
            element = {'element_name': self.read_pascal_string(),
                       'shape_name': self.read_pascal_string(),
                       'mat4': self.read_mat4(),
                       'is_visible': self.read_int(1)}
            # TODO unknown if is_visible is actually is_visible
            print("Name: " + element['element_name'])
            print("Shape name" + element['shape_name'])
            self.skip_bytes(1)  # TODO unknown

            number_of_animations = self.read_int(8)
            print("This model has " + str(number_of_animations) + " animations")
            animations = []
            for _ in range(0, number_of_animations):
                current_animation = {'animation_name': self.read_pascal_string(),
                                     'animation_file_name': self.read_pascal_string()}
                print("Animation name: " + current_animation['animation_name'])
                print("Animation filename: " + current_animation['animation_file_name'])
                animations.append(current_animation)
            element['animations'] = animations
            sgi_data.append(element)
            print("================================")

        print("Reading SGI file finished")
        return sgi_data

    def read_pascal_string(self):
        """
        Read long+ASCII String from internal file
        :return: String
        """
        return self.read_string(self.read_int(8))

    def read_mat4(self):
        mat = [self.read_float() for _ in range(0, 16)]
        # Column major, apparently
        return [[mat[0], mat[4], mat[8], mat[12]],
                [mat[1], mat[5], mat[9], mat[13]],
                [mat[2], mat[6], mat[10], mat[14]],
                [mat[3], mat[7], mat[11], mat[15]]]


# Updated for Blender 4.4
def createRig(name, origin, boneTable):
    # Create armature and object
    arm_data = bpy.data.armatures.new(name+'Amt')
    arm_obj = bpy.data.objects.new(name, arm_data)
    
    # Link armature to scene
    bpy.context.collection.objects.link(arm_obj)
    
    # Make armature active and enter edit mode
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.show_in_front = True  # X-ray equivalent
    arm_obj.location = origin
    
    # Enter edit mode and create bones
    bpy.ops.object.mode_set(mode='EDIT')
    
    for (bname, pname, vector) in boneTable:
        bone = arm_data.edit_bones.new(bname)
        if pname:
            parent = arm_data.edit_bones[pname]
            bone.parent = parent
            bone.head = parent.tail
            bone.use_connect = False
            (trans, rot, scale) = parent.matrix.decompose()
        else:
            bone.head = (0,0,0)
            rot = Matrix.Translation((0,0,0))  # identity matrix
        bone.tail = rot @ Vector(vector) + bone.head
    
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm_obj
