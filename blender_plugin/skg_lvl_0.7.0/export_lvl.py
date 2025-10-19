import bpy
import bmesh
import os
import struct
import mathutils

# --- Constants --- 
SGI_VERSION = b"2.0"
SGM_VERSION = b"2.0"
BIG_ENDIAN = '>' # Network byte order

# Полифилл для совместимости с Blender 4.4
# Добавляем метод-заглушку split_normals_calc к классу Mesh
# Это нужно, поскольку в сообщении об ошибке упоминается именно этот метод
if not hasattr(bpy.types.Mesh, 'split_normals_calc'):
    def split_normals_calc_polyfill(self):
        print("Using polyfill for split_normals_calc")
        # Используем современный метод, если он доступен
        if hasattr(self, 'calc_normals_split'):
            return self.calc_normals_split()
        print("Warning: Neither split_normals_calc nor calc_normals_split available")
    
    # Добавляем метод к классу Mesh
    bpy.types.Mesh.split_normals_calc = split_normals_calc_polyfill

# Обеспечиваем обратную совместимость для обоих методов
# В сообщении об ошибке упоминается split_normals_calc, но у нас вызывается calc_normals_split
def ensure_normals_split(mesh):
    """Безопасный способ вычисления split normals, работающий в любой версии Blender"""
    try:
        # Сначала пробуем современный метод
        if hasattr(mesh, 'calc_normals_split'):
            mesh.calc_normals_split()
        # Если его нет, пробуем старый метод
        elif hasattr(mesh, 'split_normals_calc'):
            mesh.split_normals_calc()
        else:
            print("Warning: No method available for calculating split normals")
    except Exception as e:
        print(f"Error calculating split normals: {e}")

# Определяем вспомогательные функции до их использования
def get_mat4(matrix):
    # Convert Blender matrix to column-major format
    return [
        [matrix[0][0], matrix[1][0], matrix[2][0], matrix[3][0]],
        [matrix[0][1], matrix[1][1], matrix[2][1], matrix[3][1]],
        [matrix[0][2], matrix[1][2], matrix[2][2], matrix[3][2]],
        [matrix[0][3], matrix[1][3], matrix[2][3], matrix[3][3]]
    ]

def write_pascal_string(f, text):
    """Writes a string preceded by its length (Pascal style)."""
    encoded_text = text.encode('utf-8')
    f.write(struct.pack(BIG_ENDIAN + 'Q', len(encoded_text))) # Q for 64-bit length
    f.write(encoded_text)

def save_sgm(model_data, sgm_filename):
    """Saves the geometry data (.sgm.msb)."""
    print(f"  Saving SGM to {sgm_filename}...")
    os.makedirs(os.path.dirname(sgm_filename), exist_ok=True)
    
    vertices = model_data['vertex_data']['position']
    uvs = model_data['vertex_data']['uv']
    normals = model_data['vertex_data']['normals']
    colors = model_data['vertex_data']['vertex_color']
    indices = model_data['index_buffer']
    texture_name = model_data['texture_name']
    
    num_vertices = len(vertices)
    # Indices define triangles, so num_triangles is len(indices) / 3
    num_triangles = len(indices) // 3 

    # Define attributes present in the file
    attributes = [
        ("position", "fff"), # 3 floats
        ("normal", "fff"),   # 3 floats
        ("uv", "ff"),       # 2 floats
        ("color", "BBBB")   # 4 bytes (RGBA)
    ]

    with open(sgm_filename, 'wb') as f:
        # Write Vertex Data (Interleaved)
        vertex_map = {} # Map original vertex data to unique index in SGM
        unique_vertices_data = []
        sgm_indices = []
        next_sgm_index = 0

        for i in range(num_vertices):
            pos = vertices[i]
            norm = normals[i]
            uv = uvs[i]
            col = colors[i]

            # Create a tuple key for the unique vertex data
            # Convert float components to a fixed precision string to handle potential floating point inaccuracies
            # Convert Mathutils objects to tuples
            pos_tuple = tuple(f"{p:.6f}" for p in pos)
            norm_tuple = tuple(f"{n:.6f}" for n in norm)
            uv_tuple = tuple(f"{u:.6f}" for u in uv)
            # Color comes as floats [0,1], convert to int [0,255] for key comparison
            col_tuple = tuple(int(c * 255) for c in col)
            
            vertex_key = (pos_tuple, norm_tuple, uv_tuple, col_tuple)

            if vertex_key not in vertex_map:
                # New unique vertex
                vertex_map[vertex_key] = next_sgm_index
                sgm_indices.append(next_sgm_index)
                # Store data for writing later
                unique_vertices_data.append((pos, norm, uv, col))
                next_sgm_index += 1
            else:
                # Existing vertex
                sgm_indices.append(vertex_map[vertex_key])
                
        num_unique_vertices = len(unique_vertices_data)
        print(f"    Original vertices: {num_vertices}, Unique SGM vertices: {num_unique_vertices}")
        
        # Rewrite Vertex Count with unique count
        f.seek(0) # Go back to start to find where vertex count is
        write_pascal_string(f, SGM_VERSION.decode('utf-8')) # Version string
        write_pascal_string(f, model_data['texture_name'])
        # 13 unknown floats, seems to be the same in every file
        f.write(struct.pack('>fffffffffffff', 0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 90))
        # Write rest of header
        write_pascal_string(f, "float p[3],n[3],uv[2]; uchar4 c;")  # TODO Doesn't work for files with sgs
        f.write(struct.pack('>Q', 36))  # TODO doesn't work for files with sgs
        f.write(struct.pack('>Q', len(model_data['vertex_data']['position'])))  # Write number of vertices
        f.write(struct.pack('>Q', len(model_data['index_buffer'])))  # Write number of triangles (loops)
        f.write(struct.pack('>Q', 0))  # TODO doesn't work for sgs files, so, what is it?
        for vertex_index in range(len(model_data['vertex_data']['position'])):
            # Write vertex data
            f.write(struct.pack('>f', model_data['vertex_data']['position'][vertex_index][0]))
            f.write(struct.pack('>f', model_data['vertex_data']['position'][vertex_index][1]))
            f.write(struct.pack('>f', model_data['vertex_data']['position'][vertex_index][2]))

            f.write(struct.pack('>f', model_data['vertex_data']['normals'][vertex_index][0]))
            f.write(struct.pack('>f', model_data['vertex_data']['normals'][vertex_index][1]))
            f.write(struct.pack('>f', model_data['vertex_data']['normals'][vertex_index][2]))

            f.write(struct.pack('>f', model_data['vertex_data']['uv'][vertex_index][0]))
            f.write(struct.pack('>f', model_data['vertex_data']['uv'][vertex_index][1]))
            # Range in Blender: 0.0 to 1.0, Range in sgm: 0 to 255
            f.write(struct.pack('>B', round(model_data['vertex_data']['vertex_color'][vertex_index][0] * 255.0)))
            f.write(struct.pack('>B', round(model_data['vertex_data']['vertex_color'][vertex_index][1] * 255.0)))
            f.write(struct.pack('>B', round(model_data['vertex_data']['vertex_color'][vertex_index][2] * 255.0)))
            f.write(struct.pack('>B', round(model_data['vertex_data']['vertex_color'][vertex_index][3] * 255.0)))
        for triangle in model_data['index_buffer']:
            # Write index buffer
            for i in range(3):
                f.write(struct.pack('>H', triangle[i]))
        # Write the bounding box data TODO check if anything changes with files with a sgs
        for i in range(6):
            f.write(struct.pack('>f', model_data['bounding_box'][i]))
    print(f"  SGM saving finished.")

def save_sgi(sgi_elements, filename):
    """Saves the scene structure data (.sgi.msb)."""
    print(f"Saving SGI to {filename}...")
    with open(filename, 'wb') as f:
        # Write SGI Header
        write_pascal_string(f, SGI_VERSION.decode('utf-8')) # Version string
        f.write(struct.pack(BIG_ENDIAN + 'Q', len(sgi_elements))) # Number of elements
        
        # Write Element Data
        for element in sgi_elements:
            print(f"  Writing element: {element['element_name']} referencing {element['shape_name']}")
            write_pascal_string(f, element['element_name']) # Path to SGM file
            write_pascal_string(f, element['shape_name']) # Element name
            # Write Matrix (16 floats)
            for row in element['mat4']:
                for val in row:
                    f.write(struct.pack(BIG_ENDIAN + 'f', val))
            f.write(struct.pack('B', element['is_visible']))
            # unknown TODO unknown, fix it, default value 0
            f.write(struct.pack('B', 0))
            # Number of animations, 0 for now (see todo above with statement)
            n_of_animations = 0 #currently no animations, add them to sgi and sgm
            f.write(struct.pack('>Q', n_of_animations)) 
    print(f"SGI saving finished.")

def save(operator, context, filename=""):
    exported_object_count = 0
    models = {}
    sgi_elements = []
    base_dir = os.path.dirname(filename)
    for o in bpy.data.objects:
        if o.type != 'MESH':
            print("Skipped object:", o.name, "of type:", o.type)
            continue  # Skip if it's not a mesh
        print("Exporting object: " + o.name)
        models[o.name] = {}  # Each model is a dict
        model = models[o.name]
        mesh = o.data
        
        # Get texture name - UPDATED FOR BLENDER 4.2
        print("Reading material slots to find the texture")
        model['texture_name'] = None
        
        for mat_slot in o.material_slots:
            if mat_slot.material and mat_slot.material.use_nodes:
                for node in mat_slot.material.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        model['texture_name'] = os.path.splitext(node.image.name)[0]
                        print("Found an image for material: " + node.image.name)
                        break
                if model['texture_name']:
                    break

        # Debug output
        if model['texture_name']:
            print("Texture name: " + model['texture_name'])
        else:
            print("No texture found for object: " + o.name)

        # Recalculate normals - UPDATED FOR BLENDER 4.2
        ensure_normals_split(mesh)  # Calculate split vertex normals
        mesh.update()
        mesh.validate()
        
        # Get bmesh for detailed data
        bmesh_mesh = bmesh.new()
        bmesh_mesh.from_mesh(mesh)
        
        # Set name
        model['element_name'] = o.name
        model['shape_name'] = mesh.name
        
        # Set world matrix
        model['world_matrix'] = get_mat4(o.matrix_world)
        
        # Check if model is visible - UPDATED FOR BLENDER 4.2
        model['is_visible'] = 0 if o.hide_get() else 1
        
        # Animation and vertex data setup
        model['animations'] = []
        model['vertex_data'] = {
            'position': [],
            'uv': [],
            'normals': [],
            'vertex_color': []
        }
        model['index_buffer'] = []

        # UV and vertex color layers - UPDATED FOR BLENDER 4.2
        uv_layer = bmesh_mesh.loops.layers.uv.active
        if uv_layer is None and bmesh_mesh.loops.layers.uv:
            uv_layer = bmesh_mesh.loops.layers.uv[0]

        # Vertex color handling - UPDATED FOR BLENDER 4.2
        color_layers = bmesh_mesh.loops.layers.color
        vertex_color_layer = None
        if color_layers:
            # Use the first color layer (typically named 'Col')
            vertex_color_layer = color_layers[0]

        print("Object has " + str(len(bmesh_mesh.faces)) + " faces")
        
        # Go through each face
        n_of_shared_vertices = 0
        for i, face in enumerate(bmesh_mesh.faces):
            triangle_indices = []
            triangle = face.loops
            
            # Check if loop is a triangle
            if len(triangle) != 3:
                raise ValueError("Loop != 3 vertices, triangulate / check for stray vertices; Meshname: " + model['shape_name'])
            
            # Go through each vertex in the face
            for l_i in range(3):
                triangle_vertex = triangle[l_i]
                x, y, z = triangle_vertex.vert.co[0:3]
                
                # UV data
                if uv_layer:
                    uv_data = triangle_vertex[uv_layer].uv
                    u, v = uv_data[0:2]
                else:
                    u, v = 0.0, 0.0
                    
                # Normals
                nx, ny, nz = triangle_vertex.vert.normal[0:3]
                
                # Vertex colors - UPDATED FOR BLENDER 4.2
                if vertex_color_layer:
                    color_data = triangle_vertex[vertex_color_layer]
                    # Color data is typically in SRGB, we might need to convert to linear
                    r, g, b, a = color_data[0:4]
                else:
                    r = g = b = a = 1.0

                # Find or create vertex
                found_vertex = -1
                
                for vertex_index in range(len(model['vertex_data']['position'])):
                    # Get data for existing vertex
                    pos = model['vertex_data']['position'][vertex_index]
                    uvs = model['vertex_data']['uv'][vertex_index]
                    normals = model['vertex_data']['normals'][vertex_index]
                    vertex_colors = model['vertex_data']['vertex_color'][vertex_index]
                    
                    # Check if any vertex attributes are different
                    if (pos[0] != x or pos[1] != y or pos[2] != z or 
                        uvs[0] != u or uvs[1] != v or
                        normals[0] != nx or normals[1] != ny or normals[2] != nz or
                        vertex_colors[0] != r or vertex_colors[1] != g or 
                        vertex_colors[2] != b or vertex_colors[3] != a):
                        continue
                        
                    # Found matching vertex
                    found_vertex = vertex_index
                    n_of_shared_vertices += 1
                    break

                if found_vertex == -1:
                    model['vertex_data']['position'].append([x, y, z])
                    model['vertex_data']['uv'].append([u, v])
                    model['vertex_data']['normals'].append([nx, ny, nz])
                    model['vertex_data']['vertex_color'].append([r, g, b, a])
                    found_vertex = len(model['vertex_data']['position']) - 1

                triangle_indices.append(found_vertex)

            model['index_buffer'].append(triangle_indices)

        print("The current model contains " + str(n_of_shared_vertices) + " shared vertices")

        # Write bounding box data
        x_min = y_min = z_min = float('inf')
        x_max = y_max = z_max = float('-inf')
        
        for position in model['vertex_data']['position']:
            x_min = min(x_min, position[0])
            x_max = max(x_max, position[0])
            y_min = min(y_min, position[1])
            y_max = max(y_max, position[1])
            z_min = min(z_min, position[2])
            z_max = max(z_max, position[2])

        model['bounding_box'] = [x_min, y_min, z_min, x_max, y_max, z_max]

        # Clean up bmesh
        bmesh_mesh.free()
        
        print("=====================================")

        # --- Save SGM --- 
        # Sanitize object name for filename
        # Получаем имя формы из данных меша и санитируем его
        shape_name = o.data.name if o.data else o.name
        sanitized_shape_name = "".join(c for c in shape_name if c.isalnum() or c in ('_', '-')).rstrip()
        if not sanitized_shape_name: 
            sanitized_shape_name = f"mesh_{exported_object_count}" # Fallback name

        # Используем санитированное имя формы для имени файла SGM
        sgm_filename = os.path.join(base_dir, sanitized_shape_name + ".sgm.msb")
        try:
            save_sgm(model, sgm_filename)
        except Exception as e:
            print(f"  ERROR saving SGM for {o.name}: {e}")
            continue # Skip this object if SGM fails

        # --- Prepare SGI Element --- 
        sgi_element = {        
            'element_name': o.name,    # Имя объекта в сцене
            'shape_name': shape_name,  # Имя формы (без изменений)
            'mat4': get_mat4(o.matrix_world), # World matrix
            'is_visible': model['is_visible']
        }
        sgi_elements.append(sgi_element)
        exported_object_count += 1

    # --- Save SGI --- 
    if not sgi_elements:
        print("No mesh objects found to export.")
        return {'CANCELLED'}
        
    try:
        save_sgi(sgi_elements, filename)
    except Exception as e:
        print(f"ERROR saving SGI file: {e}")
        return {'CANCELLED'}

    print(f"Export finished successfully. {exported_object_count} objects exported.")
    return {'FINISHED'}