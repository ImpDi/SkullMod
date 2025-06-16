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
        # Write SGM Header
        write_pascal_string(f, SGM_VERSION.decode('utf-8')) # Version string
        write_pascal_string(f, texture_name) # Texture name string
        
        # Write Attribute Info
        f.write(struct.pack(BIG_ENDIAN + 'Q', len(attributes))) # Number of attributes
        for name, fmt in attributes:
            write_pascal_string(f, name) # Attribute name
            f.write(struct.pack(BIG_ENDIAN + 'Q', struct.calcsize(fmt))) # Size of attribute data
        
        # Write Vertex Count
        f.write(struct.pack(BIG_ENDIAN + 'Q', num_vertices)) # Number of vertices

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
        write_pascal_string(f, SGM_VERSION.decode('utf-8'))
        write_pascal_string(f, texture_name)
        f.write(struct.pack(BIG_ENDIAN + 'Q', len(attributes)))
        for name, fmt in attributes:
             write_pascal_string(f, name)
             f.write(struct.pack(BIG_ENDIAN + 'Q', struct.calcsize(fmt)))
        # Now write the correct vertex count
        f.write(struct.pack(BIG_ENDIAN + 'Q', num_unique_vertices))
        # Go to end to continue writing
        f.seek(0, os.SEEK_END)

        # Write the unique vertex data
        for pos, norm, uv, col in unique_vertices_data:
            f.write(struct.pack(BIG_ENDIAN + 'fff', pos.x, pos.y, pos.z))
            f.write(struct.pack(BIG_ENDIAN + 'fff', norm.x, norm.y, norm.z))
            f.write(struct.pack(BIG_ENDIAN + 'ff', uv[0], uv[1]))
            f.write(struct.pack(BIG_ENDIAN + 'BBBB',
                                int(col[0] * 255),
                                int(col[1] * 255),
                                int(col[2] * 255),
                                int(col[3] * 255) if len(col) > 3 else 255))

        # Write Triangle Count
        num_sgm_triangles = len(sgm_indices) // 3
        f.write(struct.pack(BIG_ENDIAN + 'Q', num_sgm_triangles)) # Number of triangles

        # Write Index Buffer using SGM indices
        for idx in sgm_indices:
            f.write(struct.pack(BIG_ENDIAN + 'L', idx)) # L for unsigned long (assuming 32-bit indices)
            
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
            write_pascal_string(f, element['shape_name']) # Path to SGM file
            write_pascal_string(f, element['element_name']) # Element name
            # Write Matrix (16 floats)
            for row in element['mat4']:
                for val in row:
                    f.write(struct.pack(BIG_ENDIAN + 'f', val))
            f.write(struct.pack(BIG_ENDIAN + 'Q', element['is_visible'])) # Visibility flag
    print(f"SGI saving finished.")

def save(operator, context, filename=""):
    """Exports the scene to SGI/SGM format."""
    print(f"Starting export to {filename}")
    sgi_elements = []
    exported_object_count = 0
    base_dir = os.path.dirname(filename)
    meshes_dir = os.path.join(base_dir, "meshes")
    os.makedirs(meshes_dir, exist_ok=True)
    print(f"Meshes will be saved in: {meshes_dir}")

    # Ensure we are in object mode before iterating
    if context.object and context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    for o in context.scene.objects: # Iterate through objects in the current scene
        if o.type != 'MESH':
            print(f"Skipped object: {o.name} (Type: {o.type})")
            continue
        
        print(f"Processing object: {o.name}")
        
        # Make a temporary copy for mesh processing to avoid modifying original
        depsgraph = context.evaluated_depsgraph_get()
        obj_eval = o.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        if not mesh:
            print(f"  Warning: Could not get mesh data for {o.name}")
            continue
            
        model_data = {}

        # --- Texture Name --- 
        print("  Reading materials to find the texture...")
        model_data['texture_name'] = None
        for mat_slot in o.material_slots:
            if mat_slot.material and mat_slot.material.use_nodes:
                for node in mat_slot.material.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        model_data['texture_name'] = os.path.splitext(node.image.name)[0]
                        print(f"    Found texture: {model_data['texture_name']}")
                        break # Assuming one texture per object for now
            if model_data['texture_name']:
                break
        if not model_data['texture_name']:
            print(f"  Warning: No texture found for {o.name}. Using default.")
            model_data['texture_name'] = "default_texture"

        # --- Normals --- 
        print("  Calculating split normals...")
        ensure_normals_split(mesh)
        try:
            has_custom_normals = hasattr(mesh, 'has_custom_normals') and mesh.has_custom_normals
            if has_custom_normals:
                print("    Object has custom normals")
        except Exception as e:
            print(f"    Warning: Could not process custom normals: {e}")

        # --- Visibility --- 
        is_visible = 1 if not (o.hide_get() or o.hide_render) else 0
        print(f"  Visibility: {is_visible}")

        # --- BMesh and Vertex Data Collection --- 
        print("  Collecting vertex data using BMesh...")
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.transform(o.matrix_world) # Apply world transform directly to vertices
        bm.normal_update()

        model_data['vertex_data'] = {
            'position': [], 'uv': [], 'normals': [], 'vertex_color': []
        }
        model_data['index_buffer'] = []

        uv_layer = bm.loops.layers.uv.active
        color_layer = bm.loops.layers.color.active # Try getting active color layer
        if not color_layer and len(mesh.color_attributes) > 0:
             # Fallback for Blender 4.4+ attribute system if bmesh layer not found
             print("    Using mesh color_attributes as fallback")
             color_attribute_data = mesh.color_attributes.active_color.data
        else:
            color_attribute_data = None
            if color_layer:
                 print(f"    Using BMesh color layer: {color_layer.name}")
            else:
                 print("    No active color layer or attribute found.")

        if not uv_layer:
            print("  Warning: No active UV layer found.")
            
        loop_map = {} # Map bmesh loop to index in our buffer
        vert_map = {} # Map bmesh vert to index in our buffer
        v_idx_counter = 0
        l_idx_counter = 0
        vert_data_list = []

        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            face_indices = []
            for loop in face.loops:
                vert = loop.vert
                vert_key = vert.index 

                if vert_key not in vert_map:
                     # New vertex encountered
                     vert_map[vert_key] = v_idx_counter
                     pos = vert.co
                     norm = vert.normal 

                     uv = loop[uv_layer].uv if uv_layer else mathutils.Vector((0.0, 0.0))

                     # Get color
                     color_val = (1.0, 1.0, 1.0, 1.0) # Default white
                     if color_layer: # Prioritize BMesh color layer
                          color_val = loop[color_layer]
                     elif color_attribute_data: # Fallback to mesh attribute data
                          try:
                               color_val = color_attribute_data[loop.index].color
                          except (AttributeError, IndexError):
                               pass # Keep default color
                               
                     vert_data_list.append({
                          'position': pos,
                          'uv': uv,
                          'normal': norm,
                          'color': color_val
                     })
                     current_vert_index = v_idx_counter
                     v_idx_counter += 1
                else:
                     # Vertex already processed
                     current_vert_index = vert_map[vert_key]
                
                face_indices.append(current_vert_index)
                l_idx_counter += 1
                
            # Add face indices (assuming triangles)
            if len(face_indices) == 3:
                 model_data['index_buffer'].extend(face_indices)
            elif len(face_indices) > 3: # Triangulate polygon if needed
                 print(f"    Triangulating face with {len(face_indices)} verts")
                 for i in range(1, len(face_indices) - 1):
                     model_data['index_buffer'].extend([face_indices[0], face_indices[i], face_indices[i+1]])
                     
        # Populate model_data vertex arrays from collected unique data
        for vd in vert_data_list:
            model_data['vertex_data']['position'].append(vd['position'])
            model_data['vertex_data']['uv'].append(vd['uv'])
            model_data['vertex_data']['normals'].append(vd['normal'])
            model_data['vertex_data']['vertex_color'].append(vd['color'])
            
        print(f"  Collected data for {len(model_data['vertex_data']['position'])} vertices and {len(model_data['index_buffer'])} indices.")

        bm.free()
        obj_eval.to_mesh_clear()

        # --- Save SGM --- 
        # Sanitize object name for filename
        sanitized_name = "".join(c for c in o.name if c.isalnum() or c in ('_', '-')).rstrip()
        if not sanitized_name: sanitized_name = f"mesh_{exported_object_count}" # Fallback name
        sgm_filename = os.path.join(meshes_dir, sanitized_name + ".sgm.msb")
        try:
            save_sgm(model_data, sgm_filename)
        except Exception as e:
            print(f"  ERROR saving SGM for {o.name}: {e}")
            continue # Skip this object if SGM fails

        # --- Prepare SGI Element --- 
        sgi_element = {
            'shape_name': os.path.join("meshes", sanitized_name + ".sgm.msb").replace('\\', '/'), # Use relative path with forward slashes
            'element_name': o.name, # Original object name
            'mat4': get_mat4(o.matrix_world), # World matrix
            'is_visible': is_visible
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