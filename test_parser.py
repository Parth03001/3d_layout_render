import sys
import os
import logging

# Add current directory to path so we can import backend modules
sys.path.append(os.path.join(os.getcwd(), 'backend'))

import vrml_parser

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s')

def test():
    path = r'C:\Users\50014665\Downloads\layou3d.wrl'
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return

    print(f"Starting parsing of {path} ...")
    try:
        scene = vrml_parser.load_vrml_as_scene(path)
        if scene.geometry:
            mesh = list(scene.geometry.values())[0]
            print(f"SUCCESS!")
            print(f"Vertices: {len(mesh.vertices):,}")
            print(f"Faces: {len(mesh.faces):,}")
        else:
            print("No geometry found in scene.")
    except Exception as e:
        print(f"Error during parsing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
