import os
import bpy
from bpy.props import (CollectionProperty,
                       StringProperty)
from bpy_extras.io_utils import (ImportHelper,
                                 ExportHelper)

# Добавляем полифиллы для методов, удаленных в Blender 4.1+
def apply_compatibility_patches():
    """Добавляет совместимость с API Blender 4.0 и ниже"""
    # Проверяем, нужны ли патчи (работаем ли мы в Blender 4.1+)
    blender_version = bpy.app.version
    needs_patches = blender_version[0] > 4 or (blender_version[0] == 4 and blender_version[1] >= 1)
    
    if not needs_patches:
        return
        
    # Добавляем патч для split_normals_calc
    if not hasattr(bpy.types.Mesh, 'split_normals_calc'):
        def split_normals_calc_polyfill(self):
            print("Using patched split_normals_calc method")
            if hasattr(self, 'calc_normals_split'):
                return self.calc_normals_split()
            print("Warning: Cannot calculate split normals in this Blender version")
        bpy.types.Mesh.split_normals_calc = split_normals_calc_polyfill
    
    # Добавляем патч для create_normals_split если такого метода нет
    if not hasattr(bpy.types.Mesh, 'create_normals_split'):
        def create_normals_split_polyfill(self):
            print("Using patched create_normals_split method")
            # В новых версиях это делается автоматически
            pass
        bpy.types.Mesh.create_normals_split = create_normals_split_polyfill
    
    # Другие патчи по необходимости...
    print("Applied compatibility patches for Blender 4.1+ API changes")

# Применяем патчи при импорте модуля
apply_compatibility_patches()

bl_info = {
    "name": "Skullgirls .lvl plugin",
    "author": "0xFAIL",
    "version": (0, 6, 2),
    "blender": (4, 2, 0),
    "category": "Import-Export",
    "location": "File > Import/Export",
    "description": "Import Skullgirls stages. Updated for Blender 4.4"
}

class ImportLVL(bpy.types.Operator, ImportHelper):
    """Load a lvl file and all the other stuff around it"""
    bl_idname = "import_mesh.skglvl"
    bl_label = "Import LVL"
    bl_options = {'UNDO'}

    files: CollectionProperty(
        name="File Path",
        description="File path used for importing the lvl file",
        type=bpy.types.OperatorFileListElement
    )

    directory: StringProperty()

    filename_ext = '.lvl'
    filter_glob: StringProperty(default='*.lvl', options={'HIDDEN'})

    def execute(self, context):
        from . import import_lvl
        paths = [os.path.join(self.directory, name.name)
                 for name in self.files]
        if not paths:
            paths.append(self.filepath)

        for path in paths:
            import_lvl.load(self, context, path)
        return {'FINISHED'}


class ExportLVL(bpy.types.Operator, ExportHelper):
    """Export current scene as a sgi file"""
    bl_idname = "export_mesh.skglvl"
    bl_label = "Export sgi"

    filename_ext = ".sgi.msb"
    filter_glob: StringProperty(default="*.sgi.msb", options={'HIDDEN'})

    def execute(self, context):
        from . import export_lvl
        filepath = self.filepath
        filepath = bpy.path.ensure_ext(filepath, self.filename_ext)

        return export_lvl.save(self, context, filepath)


def menu_func_import(self, context):
    self.layout.operator(ImportLVL.bl_idname, text="Skullgirls stage (.lvl)")


def menu_func_export(self, context):
    self.layout.operator(ExportLVL.bl_idname, text="Skullgirls stage info (.sgi.msb)")


# New registration system
classes = (
    ImportLVL,
    ExportLVL,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)

if __name__ == "__main__":
    register()
