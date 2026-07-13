#!/usr/bin/env python3
"""Download an icon from a URL and optionally create a yellow-tinted version for tray app."""

import argparse
import urllib.request
import ssl
from PIL import Image
import io
import os
from urllib.parse import urlparse


def download_image(url):
    """Download image from URL."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
        return Image.open(io.BytesIO(response.read()))


def fetch_favicon(url):
    """Try to fetch favicon from a website URL."""
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    # Common favicon locations to try
    favicon_paths = [
        '/favicon.ico',
        '/favicon.png',
        '/apple-touch-icon.png',
        '/apple-touch-icon-precomposed.png',
    ]

    for path in favicon_paths:
        try:
            favicon_url = base_url + path
            print(f"  Trying: {favicon_url}")
            return download_image(favicon_url), favicon_url
        except Exception:
            continue

    return None, None


def shift_to_yellow(img):
    """Shift image colors to yellow while preserving transparency."""
    img = img.convert('RGBA')
    pixels = img.load()

    width, height = img.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]

            if a == 0:
                continue

            luminance = (r * 0.299 + g * 0.587 + b * 0.114)
            new_r = int(min(255, luminance * 1.2))
            new_g = int(min(255, luminance * 1.0))
            new_b = int(luminance * 0.1)

            pixels[x, y] = (new_r, new_g, new_b, a)

    return img


def main():
    parser = argparse.ArgumentParser(
        description='Download an icon and create a yellow tray icon version.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python download_icon.py https://example.com/logo.png
  python download_icon.py https://example.com --favicon
  python download_icon.py https://example.com/icon.png -o my_icon
  python download_icon.py https://example.com/icon.png --no-yellow
        '''
    )
    parser.add_argument('url', help='URL of the icon image, or website URL if using --favicon')
    parser.add_argument('-o', '--output', default='tray_icon',
                        help='Output filename (without extension). Default: tray_icon')
    parser.add_argument('--favicon', action='store_true',
                        help='Auto-detect favicon from website URL')
    parser.add_argument('--no-yellow', action='store_true',
                        help='Skip creating yellow-tinted version')
    parser.add_argument('--no-ico', action='store_true',
                        help='Skip creating .ico file')

    args = parser.parse_args()

    assets_dir = os.path.dirname(os.path.abspath(__file__))
    assets_path = os.path.join(assets_dir, 'assets')
    os.makedirs(assets_path, exist_ok=True)

    # Download the image
    if args.favicon:
        print(f"Searching for favicon at {args.url}...")
        original, found_url = fetch_favicon(args.url)
        if original is None:
            print("Error: Could not find favicon. Try providing a direct image URL.")
            return 1
        print(f"Found favicon: {found_url}")
    else:
        print(f"Downloading: {args.url}")
        try:
            original = download_image(args.url)
        except Exception as e:
            print(f"Error downloading image: {e}")
            return 1

    # Save original
    original_path = os.path.join(assets_path, f'{args.output}_original.png')
    original.save(original_path)
    print(f"Saved original: {original_path}")

    if not args.no_yellow:
        print("Creating yellow-tinted version...")
        yellow = shift_to_yellow(original.copy())

        # Save yellow PNG
        yellow_path = os.path.join(assets_path, f'{args.output}.png')
        yellow.save(yellow_path)
        print(f"Saved yellow icon: {yellow_path}")

        # Create ICO for Windows
        if not args.no_ico:
            ico_path = os.path.join(assets_path, f'{args.output}.ico')
            sizes = [(16, 16), (32, 32), (48, 48), (64, 64)]
            icons = [yellow.resize(size, Image.Resampling.LANCZOS) for size in sizes]
            icons[0].save(ico_path, format='ICO', sizes=[(s, s) for s, _ in sizes])
            print(f"Saved ICO: {ico_path}")
    else:
        # Save original as the main icon
        if not args.no_ico:
            ico_path = os.path.join(assets_path, f'{args.output}.ico')
            sizes = [(16, 16), (32, 32), (48, 48), (64, 64)]
            icons = [original.convert('RGBA').resize(size, Image.Resampling.LANCZOS) for size in sizes]
            icons[0].save(ico_path, format='ICO', sizes=[(s, s) for s, _ in sizes])
            print(f"Saved ICO: {ico_path}")

    print(f"\nDone! Icons saved to {assets_path}")
    return 0


if __name__ == '__main__':
    exit(main())
