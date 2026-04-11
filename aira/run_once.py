# run_once.py — run this once to create icons
from PIL import Image, ImageDraw, ImageFont
import os

os.makedirs('static/images', exist_ok=True)

for size in [192, 512]:
    img = Image.new('RGB', (size, size), '#6C63FF')
    draw = ImageDraw.Draw(img)
    # Draw lightning bolt emoji representation
    margin = size // 4
    draw.ellipse([margin, margin, size-margin, size-margin], fill='#8B5CF6')
    font_size = size // 3
    draw.text((size//2, size//2), '⚡', fill='white', anchor='mm')
    img.save(f'static/images/icon-{size}.png')
    print(f'Created icon-{size}.png')

print('Icons created!')