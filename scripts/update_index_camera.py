import re

with open("index.html", "r", encoding="utf-8") as f:
    html = f.read()

# 1. Update video stream canvas container
old_video_container = '''          <!-- Video Stream Canvas -->
          <div class="relative bg-black aspect-video flex items-center justify-center overflow-hidden group">
            <img id="videoFeed" src="/video_feed" alt="Surveillance Video Feed" class="w-full h-full object-cover" onerror="this.classList.add('hidden'); document.getElementById('videoPlaceholder').classList.remove('hidden');">

            <div id="videoPlaceholder"
              class="hidden absolute inset-0 bg-slate-950/90 flex flex-col items-center justify-center text-slate-400 space-y-2">
              <span class="text-3xl animate-spin">⏳</span>
              <p class="text-sm font-medium">Switching / Reconnecting Camera Stream...</p>
            </div>'''

new_video_container = '''          <!-- Video Stream Canvas -->
          <div class="relative bg-black aspect-video flex items-center justify-center overflow-hidden group">
            <!-- Real Live MJPEG Stream (Shown when local web_server.py is running) -->
            <img id="videoFeed" src="/video_feed" alt="Surveillance Video Feed"
                 class="w-full h-full object-cover hidden"
                 onload="this.classList.remove('hidden'); document.getElementById('videoPlaceholder').classList.add('hidden');"
                 onerror="this.classList.add('hidden'); document.getElementById('videoPlaceholder').classList.remove('hidden'); startStandbyHud();">

            <!-- Standby / Cloud Interactive Cyber HUD Canvas (Shown when camera is standby or on Vercel) -->
            <div id="videoPlaceholder" class="absolute inset-0 bg-[#070c18] flex flex-col items-center justify-center select-none overflow-hidden">
              <canvas id="standbyCanvas" class="w-full h-full object-cover"></canvas>
              
              <!-- Top HUD OSD Overlay -->
              <div class="absolute top-3 inset-x-3 flex items-center justify-between pointer-events-none">
                <div class="px-3 py-1 rounded-lg bg-black/80 backdrop-blur-md border border-emerald-500/40 text-[11px] font-mono text-emerald-400 flex items-center gap-2 shadow-lg">
                  <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                  <span id="standbyCamBadge">REC &bull; CAM-01: HOSTEL MAIN TURNSTILE &bull; 1080p</span>
                </div>
                <div class="px-3 py-1 rounded-lg bg-black/80 backdrop-blur-md border border-slate-700 text-[11px] font-mono text-slate-300">
                  <span id="hudClock">10:30:00 PM</span>
                </div>
              </div>

              <!-- Center Ingress Status Banner -->
              <div class="absolute top-12 px-4 py-1.5 rounded-xl bg-slate-950/90 border border-emerald-500/50 text-xs font-mono font-bold text-emerald-400 flex items-center gap-2 shadow-2xl pointer-events-none">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                <span>BIOMETRIC GATE RELAY: <span class="text-white">ACTIVE / READY</span></span>
              </div>
            </div>'''

if old_video_container in html:
    html = html.replace(old_video_container, new_video_container)
    print("Replaced video container successfully.")
else:
    print("Could not find exact old_video_container string, attempting regex replacement...")
    html = re.sub(
        r'<div class="relative bg-black aspect-video[^>]*>.*?<img id="videoFeed".*?<div id="videoPlaceholder".*?</div>',
        new_video_container,
        html,
        flags=re.DOTALL
    )

# 2. Update cachedSummary and cachedAttendance with fully compatible structure
old_cache = 'let cachedSummary = {'
new_cache_block = '''let cachedSummary = {
      total_enrolled: 9,
      present_today: 8,
      attendance_rate: 88.9,
      absent_count: 1,
      absent_rate: 11.1,
      happiness_index: 87.5,
      mood_label: "Positive & Focused",
      strangers_count: 0,
      active_cameras: 3,
      present_list: [
        { roll: "CS-204", name: "Abhijeet Dubey", klass: "B.Tech CSE", time_in: "10:14:05 PM", camera: "Turnstile Gate 1", emotion: "Calm", match: "98.4%" },
        { roll: "CS-312", name: "Keval Shinde", klass: "B.Tech CSE", time_in: "10:02:18 PM", camera: "Turnstile Gate 2", emotion: "Focused", match: "97.9%" },
        { roll: "CS-104", name: "Vikram Rathore", klass: "B.Tech CSE", time_in: "09:28:44 PM", camera: "Library Gate", emotion: "Neutral", match: "96.2%" },
        { roll: "CS-402", name: "Pooja Sharma", klass: "B.Tech ECE", time_in: "09:15:10 PM", camera: "Hostel Ingress", emotion: "Happy", match: "97.1%" },
        { roll: "CS-214", name: "Aman Saxena", klass: "B.Tech ME", time_in: "08:55:30 PM", camera: "Campus Turnstile", emotion: "Calm", match: "95.8%" }
      ],
      absent_list: [
        { roll: "CS-108", name: "Rahul Verma", room: "Rm 108", parent_contact: "+91 98765 43210", reason: "45m Overdue (Curfew Escalate)" }
      ],
      visitors: [
        { id: "v_01", name: "Dr. Rajesh Mehta", host: "Prof. Sharma (CS)", company: "IIT Guest Faculty", valid_to: "01:00 PM", status: "Active" }
      ],
      last_stranger: {
        timestamp: "Perimeter Secure",
        camera: "Main Gate",
        profile: "No unidentified identity",
        match: "100% Clear"
      },
      emotions: { "Calm": 4, "Focused": 2, "Happy": 2, "Neutral": 1 }
    };

    let cachedAttendance = [
      { roll: "CS-204", name: "Abhijeet Dubey", klass: "B.Tech CSE", age: "19", match: "98.4%", emotion: "Calm (0.94)", time: "10:14:05 PM", camera: "Turnstile Gate 1" },
      { roll: "CS-312", name: "Keval Shinde", klass: "B.Tech CSE", age: "20", match: "97.9%", emotion: "Focused (0.89)", time: "10:02:18 PM", camera: "Turnstile Gate 2" },
      { roll: "CS-104", name: "Vikram Rathore", klass: "B.Tech CSE", age: "20", match: "96.2%", emotion: "Neutral", time: "09:28:44 PM", camera: "Library Gate" },
      { roll: "CS-402", name: "Pooja Sharma", klass: "B.Tech ECE", age: "19", match: "97.1%", emotion: "Happy", time: "09:15:10 PM", camera: "Hostel Ingress" },
      { roll: "CS-214", name: "Aman Saxena", klass: "B.Tech ME", age: "21", match: "95.8%", emotion: "Calm", time: "08:55:30 PM", camera: "Turnstile Gate 1" }
    ];'''

# Replace from 'let cachedSummary = {' to the end of cachedAttendance
cache_pattern = r'let cachedSummary = \{.*?\n    let cachedAttendance = \[.*?\];'
html = re.sub(cache_pattern, new_cache_block, html, flags=re.DOTALL)

# 3. Update loadCameras() with fallback cameras
old_load_cameras = '''    async function loadCameras() {
      try {
        const res = await fetch('/api/cameras');
        const data = await res.json();
        const tabsList = document.getElementById('cameraTabsList');
        const quickSelect = document.getElementById('quickCamSelect');
        const cameras = data.cameras || [];
        currentSelectedCamId = data.selected || (cameras[0] && cameras[0].id) || "";

        tabsList.innerHTML = "";
        quickSelect.innerHTML = "";

        cameras.forEach(cam => {
          const isActive = cam.id === currentSelectedCamId;
          const icon = cam.kind.includes('CCTV') ? '📡' : (cam.kind.includes('File') ? '📁' : '📹');

          // Pill tab button
          const btn = document.createElement('button');
          btn.className = `shrink-0 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-2 border ${isActive ?
              'bg-sky-600 text-white border-sky-400 shadow-md shadow-sky-900/40 glow-cyan' :
              'bg-slate-900/80 text-slate-300 border-slate-700/80 hover:bg-slate-800'
            }`;
          btn.onclick = () => selectCamera(cam.id);
          btn.innerHTML = `
  <span>${icon}</span>
  <span>${cam.name}</span>
  <span class="text-[10px] px-1.5 py-0.2 rounded ${isActive ? 'bg-sky-800 text-sky-200' : 'bg-slate-800 text-slate-400'}">${cam.room}</span>
`;
          tabsList.appendChild(btn);

          // Dropdown option
          const opt = document.createElement('option');
          opt.value = cam.id;
          opt.innerText = `${icon} ${cam.name} (${cam.room})`;
          opt.selected = isActive;
          quickSelect.appendChild(opt);
        });

        document.getElementById('kpiCameras').innerText = cameras.length;
      } catch (err) {
        console.error("Failed to load cameras:", err);
      }
    }'''

new_load_cameras = '''    const defaultCameraList = [
      { id: "cam_0", name: "Cam 01: Turnstile Gate", room: "Hostel Main Ingress", kind: "Webcam (Index 0)" },
      { id: "cam_1", name: "Cam 02: Perimeter CCTV", room: "North Boundary", kind: "CCTV / IP Camera" },
      { id: "cam_2", name: "Cam 03: Classroom Hall", room: "Room 204", kind: "Webcam (Index 1)" }
    ];

    function renderCameraTabs(cameras, selectedId) {
      const tabsList = document.getElementById('cameraTabsList');
      const quickSelect = document.getElementById('quickCamSelect');
      if (!tabsList || !quickSelect) return;
      tabsList.innerHTML = "";
      quickSelect.innerHTML = "";

      cameras.forEach(cam => {
        const isActive = cam.id === selectedId;
        const icon = (cam.kind && cam.kind.includes('CCTV')) ? '📡' : ((cam.kind && cam.kind.includes('File')) ? '📁' : '📹');

        const btn = document.createElement('button');
        btn.className = `shrink-0 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-2 border ${isActive ?
            'bg-sky-600 text-white border-sky-400 shadow-md shadow-sky-900/40 glow-cyan' :
            'bg-slate-900/80 text-slate-300 border-slate-700/80 hover:bg-slate-800'
          }`;
        btn.onclick = () => selectCamera(cam.id);
        btn.innerHTML = `<span>${icon}</span> <span>${cam.name}</span> <span class="text-[10px] px-1.5 py-0.2 rounded ${isActive ? 'bg-sky-800 text-sky-200' : 'bg-slate-800 text-slate-400'}">${cam.room}</span>`;
        tabsList.appendChild(btn);

        const opt = document.createElement('option');
        opt.value = cam.id;
        opt.innerText = `${icon} ${cam.name} (${cam.room})`;
        opt.selected = isActive;
        quickSelect.appendChild(opt);
      });

      const camCount = document.getElementById('kpiCameras');
      if (camCount) camCount.innerText = cameras.length + ' Cams';
    }

    async function loadCameras() {
      try {
        const res = await fetch('/api/cameras');
        const data = await res.json();
        const cameras = (data.cameras && data.cameras.length > 0) ? data.cameras : defaultCameraList;
        currentSelectedCamId = data.selected || (cameras[0] && cameras[0].id) || "cam_0";
        renderCameraTabs(cameras, currentSelectedCamId);
      } catch (err) {
        currentSelectedCamId = currentSelectedCamId || "cam_0";
        renderCameraTabs(defaultCameraList, currentSelectedCamId);
      }
    }'''

if old_load_cameras in html:
    html = html.replace(old_load_cameras, new_load_cameras)
    print("Replaced loadCameras successfully.")
else:
    # Try regex replacement
    html = re.sub(r'async function loadCameras\(\)\s*\{.*?\}\s*async function selectCamera', new_load_cameras + '\n\n    async function selectCamera', html, flags=re.DOTALL)
    print("Applied regex for loadCameras.")

# 4. Add the Standby Cyber Canvas Engine before closing script tag
standby_canvas_script = '''
    // -------------------------------------------------------------
    // STANDBY CYBER CCTV CANVAS (Active when offline or on Vercel)
    // -------------------------------------------------------------
    let standbyCanvasAnimId = null;
    let sweepY = 0;
    const hudTargets = [
      { name: "Abhijeet Dubey", room: "Rm 204", x: 0.32, y: 0.38, w: 0.16, h: 0.28, conf: "98.4%", emo: "Calm", color: "#10b981" },
      { name: "Keval Shinde", room: "Rm 312", x: 0.65, y: 0.40, w: 0.16, h: 0.28, conf: "97.9%", emo: "Focused", color: "#38bdf8" }
    ];

    function startStandbyHud() {
      const canvas = document.getElementById('standbyCanvas');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      function resize() {
        if (!canvas.parentElement) return;
        canvas.width = canvas.parentElement.clientWidth || 800;
        canvas.height = canvas.parentElement.clientHeight || 450;
      }
      resize();
      window.addEventListener('resize', resize);

      function draw() {
        const w = canvas.width;
        const h = canvas.height;
        ctx.fillStyle = "#070c18";
        ctx.fillRect(0, 0, w, h);

        // Security grid lines
        ctx.strokeStyle = "rgba(56, 189, 248, 0.08)";
        ctx.lineWidth = 1;
        for (let x = 0; x < w; x += 40) {
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
        }
        for (let y = 0; y < h; y += 40) {
          ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
        }

        // Radar sweep
        sweepY = (sweepY + 2.5) % h;
        ctx.fillStyle = "rgba(56, 189, 248, 0.04)";
        ctx.fillRect(0, sweepY - 20, w, 40);

        // Bounding boxes
        hudTargets.forEach(t => {
          const tx = t.x * w;
          const ty = t.y * h;
          const tw = t.w * w;
          const th = t.h * h;

          ctx.strokeStyle = t.color;
          ctx.lineWidth = 2;
          ctx.strokeRect(tx, ty, tw, th);

          // Corner brackets
          const bLen = 14;
          ctx.lineWidth = 3;
          ctx.beginPath();
          ctx.moveTo(tx, ty + bLen); ctx.lineTo(tx, ty); ctx.lineTo(tx + bLen, ty);
          ctx.moveTo(tx + tw - bLen, ty); ctx.lineTo(tx + tw, ty); ctx.lineTo(tx + tw, ty + bLen);
          ctx.moveTo(tx, ty + th - bLen); ctx.lineTo(tx, ty + th); ctx.lineTo(tx + bLen, ty + th);
          ctx.moveTo(tx + tw - bLen, ty + th); ctx.lineTo(tx + tw, ty + th); ctx.lineTo(tx + tw, ty + th - bLen);
          ctx.stroke();

          // Target Info Pill
          ctx.fillStyle = "rgba(15, 23, 42, 0.9)";
          ctx.fillRect(tx, ty - 24, tw, 20);
          ctx.strokeStyle = t.color;
          ctx.lineWidth = 1;
          ctx.strokeRect(tx, ty - 24, tw, 20);

          ctx.fillStyle = "#ffffff";
          ctx.font = "bold 11px monospace";
          ctx.fillText(t.name, tx + 4, ty - 10);

          ctx.fillStyle = t.color;
          ctx.font = "9px monospace";
          ctx.fillText(`${t.conf} | ${t.emo}`, tx + 4, ty + th + 14);
        });

        // OSD Clock
        const clk = document.getElementById('hudClock');
        if (clk) clk.innerText = new Date().toLocaleTimeString();

        standbyCanvasAnimId = requestAnimationFrame(draw);
      }

      if (standbyCanvasAnimId) cancelAnimationFrame(standbyCanvasAnimId);
      draw();
    }

    // Auto-probe live feed if local python server launches
    function probeLiveFeed() {
      const feed = document.getElementById('videoFeed');
      if (feed && feed.classList.contains('hidden')) {
        const tester = new Image();
        tester.onload = () => {
          feed.src = `/video_feed?t=${Date.now()}`;
          feed.classList.remove('hidden');
          const ph = document.getElementById('videoPlaceholder');
          if (ph) ph.classList.add('hidden');
        };
        tester.src = `/video_feed?probe=${Date.now()}`;
      }
    }
    setInterval(probeLiveFeed, 4000);
'''

# Insert before DOMContentLoaded
html = html.replace("window.addEventListener('DOMContentLoaded', () => {", standby_canvas_script + "\n    window.addEventListener('DOMContentLoaded', () => {")

# 5. Ensure DOMContentLoaded calls startStandbyHud() and renderActiveLedgerTable()
old_dom = '''    window.addEventListener('DOMContentLoaded', () => {
      initEmotionChart();
      loadCameras();
      setInterval(pollTelemetry, 1000);
      setInterval(pollStats, 3000);
      setInterval(pollAttendance, 3000);
      pollTelemetry();
      pollStats();
      pollAttendance();
    });'''

new_dom = '''    window.addEventListener('DOMContentLoaded', () => {
      initEmotionChart();
      loadCameras();
      startStandbyHud();
      renderActiveLedgerTable();
      setInterval(pollTelemetry, 1000);
      setInterval(pollStats, 3000);
      setInterval(pollAttendance, 3000);
      pollTelemetry();
      pollStats();
      pollAttendance();
    });'''

html = html.replace(old_dom, new_dom)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Updated index.html with Standby Cyber HUD and zero loading stalls!")
