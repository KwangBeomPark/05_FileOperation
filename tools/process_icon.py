import sys
import os
from PIL import Image

def remove_background_and_crop(input_path, output_png_paths, output_ico_paths):
    img = Image.open(input_path).convert("RGBA")
    
    # 1. Convert near-white background pixels to transparent
    data = img.getdata()
    new_data = []
    
    for item in data:
        r, g, b, a = item
        # Aggressively remove any bright background (Apple style light backgrounds)
        if r > 220 and g > 220 and b > 220:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append((r, g, b, 255))
            
    img.putdata(new_data)
    
    # 2. Get bounding box of non-transparent area and tight crop
    bbox = img.getbbox()
    if bbox:
        # EXACT crop, NO padding to make it maximum size
        cropped_img = img.crop(bbox)
    else:
        cropped_img = img
        
    # Make square aspect ratio for clean icon layout
    w, h = cropped_img.size
    max_dim = max(w, h)
    square_img = Image.new("RGBA", (max_dim, max_dim), (0, 0, 0, 0))
    offset = ((max_dim - w) // 2, (max_dim - h) // 2)
    square_img.paste(cropped_img, offset)
    
    # Resize to standard high-res 512x512
    final_png = square_img.resize((512, 512), Image.Resampling.LANCZOS)
    
    # Save PNGs
    for p in output_png_paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        final_png.save(p, format="PNG")
        print(f"Saved PNG: {p}")
        
    # Save ICOs
    icon_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    for ico_p in output_ico_paths:
        os.makedirs(os.path.dirname(ico_p), exist_ok=True)
        final_png.save(ico_p, format="ICO", sizes=icon_sizes)
        print(f"Saved ICO: {ico_p}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python process_icon.py <input_png>")
        sys.exit(1)
        
    input_file = sys.argv[1]
    
    png_targets = [
        "c:/Dev/GitHub/05_FileOperation/src/assets/icon.png",
        "c:/Dev/GitHub/05_FileOperation/assets/icon.png"
    ]
    ico_targets = [
        "c:/Dev/GitHub/05_FileOperation/src/assets/icon.ico",
        "c:/Dev/GitHub/05_FileOperation/assets/icon.ico"
    ]
    
    remove_background_and_crop(input_file, png_targets, ico_targets)
