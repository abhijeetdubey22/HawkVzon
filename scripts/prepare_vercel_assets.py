import base64
import os
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
deck_src = os.path.join(BASE_DIR, "exports", "HawkVzon_Startup_Buildathon_Deck.html")
banner_path = os.path.join(BASE_DIR, "exports", "startup_buildathon_top_banner.png")
deck_dst = os.path.join(BASE_DIR, "deck.html")

if os.path.exists(deck_src):
    with open(deck_src, "r", encoding="utf-8") as f:
        content = f.read()

    if os.path.exists(banner_path):
        with open(banner_path, "rb") as bf:
            b64_str = base64.b64encode(bf.read()).decode("utf-8")
        content = content.replace('src="startup_buildathon_top_banner.png"', f'src="data:image/png;base64,{b64_str}"')

    with open(deck_dst, "w", encoding="utf-8") as f:
        f.write(content)
    print("Created deck.html:", os.path.getsize(deck_dst), "bytes")

logo_src = os.path.join(BASE_DIR, "exports", "HawkVzon_Logo_Showcase.html")
logo_dst = os.path.join(BASE_DIR, "logo.html")
if os.path.exists(logo_src):
    shutil.copyfile(logo_src, logo_dst)
    print("Created logo.html:", os.path.getsize(logo_dst), "bytes")
