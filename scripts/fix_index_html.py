
import re

with open("index.html", "r", encoding="utf-8") as f:
    text = f.read()

start_idx = text.find("<!DOCTYPE html>")
end_idx = text.find("</html>")
if start_idx == -1 or end_idx == -1:
    print("Could not find HTML boundaries!")
    exit(1)

end_idx += len("</html>")
raw_html = text[start_idx:end_idx]

# Unindent common 10-space leading indent
cleaned_lines = []
for line in raw_html.splitlines():
    if line.startswith("          "):
        cleaned_lines.append(line[10:])
    elif line.startswith("        "):
        cleaned_lines.append(line[8:])
    elif line.startswith("      "):
        cleaned_lines.append(line[6:])
    else:
        cleaned_lines.append(line)

html = "\n".join(cleaned_lines)

# 1. Update title and subtitle
html = html.replace(
    "<title>Autonomous AI Surveillance & Attendance Command Center</title>",
    "<title>🦅 HawkVzon AI — Campus AI Surveillance & Principal Command Center</title>"
)

# 2. Add Pitch Deck link and GitHub button into header actions
old_header_actions = '<div class="flex items-center gap-2.5">'
new_header_actions = '''<div class="flex items-center gap-2.5">
        <a href="/deck.html" target="_blank" class="px-3.5 py-2 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs font-semibold transition flex items-center gap-1.5 shadow-md shadow-purple-900/40">
          <span>📑</span> <span class="hidden sm:inline">Pitch Deck</span>
        </a>
        <a href="https://github.com/abhijeetdubey22/HawkVzon" target="_blank" class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition" title="GitHub Repository">
          <svg class="w-4 h-4 fill-current" viewBox="0 0 24 24"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
        </a>'''
html = html.replace(old_header_actions, new_header_actions, 1)

# 3. Enhance video feed with graceful fallback if camera stream not active (e.g. Vercel)
old_img = '<img id="videoFeed" src="/video_feed" alt="Surveillance Video Feed"\n                        class="w-full h-full object-cover">'
new_img = '''<img id="videoFeed" src="/video_feed" alt="Surveillance Video Feed"
                        class="w-full h-full object-cover"
                        onerror="this.classList.add('hidden'); document.getElementById('videoPlaceholder').classList.remove('hidden');">'''
if old_img in html:
    html = html.replace(old_img, new_img)
else:
    # regex fallback
    html = re.sub(
        r'<img id="videoFeed" src="/video_feed"[^>]*>',
        '<img id="videoFeed" src="/video_feed" alt="Surveillance Video Feed" class="w-full h-full object-cover" onerror="this.classList.add(\'hidden\'); document.getElementById(\'videoPlaceholder\').classList.remove(\'hidden\');">',
        html
    )

# 4. Prepopulate cachedSummary so default view is rich and complete on load
old_cache_decl = 'let cachedSummary = {};'
new_cache_decl = '''let cachedSummary = {
      total_enrolled: 9,
      present_today: 8,
      attendance_rate: 88.9,
      absent_count: 1,
      absent_rate: 11.1,
      happiness_index: 86.5,
      mood_label: "Positive & Focused",
      strangers_count: 0,
      active_cameras: 3,
      present_list: [
        { name: "Abhijeet Dubey", roll: "CS-204", time: "10:14:05 PM", emotion: "Calm", conf: "98.4%", status: "Present" },
        { name: "Keval Shinde", roll: "CS-312", time: "10:02:18 PM", emotion: "Focused", conf: "97.9%", status: "Present" },
        { name: "Vikram Rathore", roll: "CS-104", time: "09:28:44 PM", emotion: "Neutral", conf: "96.2%", status: "Present" },
        { name: "Pooja Sharma", roll: "CS-402", time: "09:15:10 PM", emotion: "Happy", conf: "97.1%", status: "Present" },
        { name: "Aman Saxena", roll: "CS-214", time: "08:55:30 PM", emotion: "Calm", conf: "95.8%", status: "Present" }
      ],
      absent_list: [
        { name: "Rahul Verma", roll: "CS-108", room: "Rm 108", parent_contact: "+91 98765 43210", reason: "Unaccounted" }
      ],
      visitors: [
        { id: "v_01", name: "Dr. Rajesh Mehta", host: "Prof. Sharma (CS)", company: "IIT Guest Faculty", valid_to: "01:00 PM", status: "Active" }
      ],
      last_stranger: {
        timestamp: "No Perimeter Intrusion",
        camera: "Main Gate Secure",
        profile: "No unidentified identity",
        match: "100% Clear",
        photo: ""
      },
      emotions: { "Calm": 4, "Focused": 2, "Happy": 2, "Neutral": 1 }
    };
    let cachedAttendance = [
      { name: "Abhijeet Dubey", roll: "CS-204", timestamp: "10:14:05 PM", emotion: "Calm (0.94)", status: "Verified Entry", camera: "Turnstile Gate 1" },
      { name: "Keval Shinde", roll: "CS-312", timestamp: "10:02:18 PM", emotion: "Focused (0.89)", status: "Verified Entry", camera: "Turnstile Gate 2" },
      { name: "Vikram Rathore", roll: "CS-104", timestamp: "09:28:44 PM", emotion: "Neutral", status: "Verified Entry", camera: "Library Gate" },
      { name: "Pooja Sharma", roll: "CS-402", timestamp: "09:15:10 PM", emotion: "Happy", status: "Verified Entry", camera: "Hostel Ingress" }
    ];'''
html = html.replace(old_cache_decl, new_cache_decl, 1)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Fixed index.html successfully! Total size:", len(html), "bytes.")
