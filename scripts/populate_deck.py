import zipfile, os, shutil
import xml.etree.ElementTree as ET

namespaces = {
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'p14': 'http://schemas.microsoft.com/office/powerpoint/2010/main',
    'p15': 'http://schemas.microsoft.com/office/powerpoint/2012/main'
}
for prefix, uri in namespaces.items():
    ET.register_namespace(prefix, uri)

src_pptx = r'C:\Users\Abhijeet\.gemini\antigravity\brain\27181280-b746-469d-ba63-5708e9585a98\.user_uploaded\media_1795192774730_657e075a.pptx'
dst_pptx = r'c:\Users\Abhijeet\Desktop\face-emotion-project-paused-work\exports\HawkVzon_Google_Startup_Buildathon_Deck.pptx'

slides_data = {
    2: [
        ("TITLE", "Team & Problem Statement"),
        ("BOLD_FIELD", "Team Name: ", "HawkVzon AI"),
        ("BOLD_FIELD", "Team Size: ", "2 Members (Edge AI Engineer & Full-Stack Cloud Architect)"),
        ("BOLD_FIELD", "Track: ", "Enterprise AI & Smart Cities | Google Cloud Startup Buildathon India 2026"),
        ("BLANK", ""),
        ("BOLD", "The Problem:"),
        ("BULLET", "300,000+ teenagers live in Kota, Sikar, and coaching hubs while parents pay Rs 3L-10L/year with zero real-time visibility into their child's safety or daily return times."),
        ("BULLET", "Incumbent hardware vendors (eSSL, Matrix) dump raw Excel punch logs. Hostels still use pen-and-paper registers for night roll-call."),
        ("BULLET", "Late returns and skipped classes trigger severe parent anxiety, student distress, and reputational risk for hostel management.")
    ],
    3: [
        ("TITLE", "Brief About the Idea"),
        ("BOLD", "HawkVzon HostelOS: Full-Stack Cloud Biometric Middleware & WhatsApp Parent-Safety Platform"),
        ("BLANK", ""),
        ("BULLET", "Pure-Software Cloud Solution: Receives direct outbound HTTP POST punch events from existing Rs 12,000 eSSL and Matrix biometric turnstiles (via ADMS protocol). Zero local PC servers or relay hardware required."),
        ("BULLET", "Reassuring Parent Alerts: Dispatches an automated 1-ping/day 'Safe Evening Return' WhatsApp notification to parents between 05:00 PM - 09:30 PM with a strict 6-hour punch cooldown (capping Meta utility costs at Rs 0.1150/msg)."),
        ("BULLET", "Parent-Approved Digital Out-Pass: Students request weekend leaves on mobile; parents approve via interactive WhatsApp buttons; turnstiles only unlatch for approved passes."),
        ("BULLET", "Night Curfew Radar & Gemini Intelligence: Live warden console reconciles attendance at 09:30 PM. Google Gemini 1.5 Flash generates a daily ~150-token executive briefing for hostel owners.")
    ],
    4: [
        ("TITLE", "Opportunities, Differentiation & USP"),
        ("BOLD_FIELD", "Market Opportunity (TAM): ", "8,000 coaching hostels & residential schools in India = Rs 34.5 Crores/year addressable ARR at Rs 30/bed/month."),
        ("BLANK", ""),
        ("BOLD", "How Different from Existing Ideas?"),
        ("BULLET", "Generic PG Apps (RentOk, Hostel Mitra): Only track rent ledger accounting; completely blind to physical turnstile hardware and security."),
        ("BULLET", "Biometric Vendors (eSSL, Matrix): Sell dumb offline hardware without WhatsApp integration; require expensive local desktop servers."),
        ("BULLET", "HawkVzon: Bridges existing biometric turnstiles directly to WhatsApp with zero hardware and 88% gross margins."),
        ("BLANK", ""),
        ("BOLD", "USP of Proposed Solution:"),
        ("BULLET", "Zero Hardware to Buy (30-minute remote setup via ADMS push). Zero local maintenance. LTV:CAC of 8.5:1.")
    ],
    5: [
        ("TITLE", "Comprehensive HostelOS Feature Matrix"),
        ("BOLD_FIELD", "1. Direct ADMS Biometric Push: ", "Ingests real-time biometric and facial punch logs directly from eSSL, Matrix, and Hikvision devices over HTTP/HTTPS."),
        ("BOLD_FIELD", "2. 1-Ping/Day Safe Return WhatsApp Ping: ", "Enforces 6-hour punch cooldown to dispatch reassuring evening notifications while capping Meta charges at Rs 414/mo per hostel."),
        ("BOLD_FIELD", "3. Two-Way Parent-Approved Out-Pass: ", "Interactive WhatsApp buttons [Approve/Reject] for parents. Turnstile unlatches automatically upon approval."),
        ("BOLD_FIELD", "4. 09:30 PM Night Curfew Radar: ", "Live warden web console highlights non-returned students with automated WhatsApp location check before escalating."),
        ("BOLD_FIELD", "5. Automated Monthly UPI Rent Reminders: ", "Pre-scheduled WhatsApp payment reminders with embedded UPI/QR links on 1st, 5th, and 7th of every month."),
        ("BOLD_FIELD", "6. Google Gemini 1.5 Flash Nightly Digest: ", "Generates daily 10:00 PM executive safety briefings (~150 tokens) summarizing curfew compliance and room anomalies.")
    ],
    6: [
        ("TITLE", "End-to-End Operational Process Flow"),
        ("BOLD", "Workflow Architecture:"),
        ("BULLET", "Step 1 (Physical Punch): Student verifies face/fingerprint at turnstile -> Device fires HTTP POST payload to cloud endpoint."),
        ("BULLET", "Step 2 (Rate-Limiter & Deduplication): Redis cache verifies 6-hr cooldown window and roster enrollment status in <5ms."),
        ("BULLET", "Step 3 (Parent Notification): Meta WhatsApp Cloud API delivers utility template message to parent phone in <3 seconds."),
        ("BULLET", "Step 4 (Night Reconciliation): At 09:30 PM curfew, warden web console flags unreturned students and initiates escalation."),
        ("BULLET", "Step 5 (Executive Synthesis): Google Gemini 1.5 Flash aggregates daily logs at 10:00 PM into an executive digest.")
    ],
    7: [
        ("TITLE", "Wireframes & Interface Mocks"),
        ("BOLD", "1. Warden Night Curfew Console (Web Interface on Port 5000):"),
        ("BULLET", "Header: Total Beds (120) | In Hostel (114) | Curfew Alert (6 students flagged late past 09:30 PM)."),
        ("BULLET", "Live Action Table: Student Name, Room Number, Out Time, Delay Status, and One-Click WhatsApp Ping / Warden Call."),
        ("BLANK", ""),
        ("BOLD", "2. Parent WhatsApp Interactive Notification:"),
        ("BULLET", "Verified Business Badge: 'HawkVzon Verified Safety Bot'"),
        ("BULLET", "Message: 'Namaste Mr. Sharma, Safe Arrival Confirmed: Your ward Abhijeet has safely checked into Kota Boys Hostel at 07:14 PM. Gate: Turnstile 1.'")
    ],
    8: [
        ("TITLE", "Edge-to-Cloud System Architecture"),
        ("BOLD", "3-Tier Hybrid Architecture:"),
        ("BULLET", "Tier 1 - Device Edge: Existing eSSL / Matrix turnstiles and RTSP IP cameras. Communicates via outbound HTTP/TCP push (zero port forwarding)."),
        ("BULLET", "Tier 2 - Middleware & Security: Python 3.10 asynchronous server backed by Redis (rate limiting) and Fernet AES-256 encrypted biometric token vault."),
        ("BULLET", "Tier 3 - Dispatch & Intelligence: Meta WhatsApp Cloud API for sub-3s delivery + Google Cloud Gemini 1.5 Flash for daily curfew intelligence."),
        ("BLANK", ""),
        ("BOLD_FIELD", "Data Privacy & Compliance: ", "Zero raw facial photographs are stored in the cloud. All matching uses one-way 128-D encrypted mathematical vectors.")
    ],
    9: [
        ("TITLE", "Technologies & Google Cloud Integrations"),
        ("BOLD_FIELD", "Google Cloud / AI: ", "Gemini 1.5 Flash (executive curfew summarization, anomaly pattern detection), Google Cloud Run & Firestore."),
        ("BOLD_FIELD", "Edge Computer Vision: ", "OpenCV & dlib ResNet (128-dimensional facial vectorization and Euclidean distance matching in <0.2ms)."),
        ("BOLD_FIELD", "Cloud Backend: ", "Python 3.10, Flask / FastAPI, Redis in-memory cache for anti-spam rate limiting."),
        ("BOLD_FIELD", "Communication API: ", "Official Meta WhatsApp Business Cloud API with pre-approved utility message templates."),
        ("BOLD_FIELD", "Security & Encryption: ", "Fernet AES-256 authenticated encryption with HMAC-SHA256 signature verification.")
    ],
    10: [
        ("TITLE", "Estimated Implementation Cost & Unit Economics"),
        ("BOLD", "Hostel Client Pricing (120-Bed Facility):"),
        ("BULLET", "Annual SaaS Subscription: Rs 43,200 / year (Rs 30/bed/month, billed upfront)."),
        ("BULLET", "One-Time Remote ADMS Setup Fee: Rs 10,000 (30-minute remote keypad configuration)."),
        ("BULLET", "Hardware Cost: Rs 0 (Hostel uses existing biometric turnstiles)."),
        ("BLANK", ""),
        ("BOLD", "Direct Annual COGS & Margins:"),
        ("BULLET", "Meta WhatsApp Utility Messages: Rs 4,968 / year (Rs 0.1150/msg capped at 1 ping/day)."),
        ("BULLET", "Google Cloud Gemini API Compute: Rs 150 / year (~150 tokens/day for nightly digest)."),
        ("BULLET", "Annual Gross Profit per Hostel: Rs 37,032 (85.7% Software Gross Margin | 8.5:1 LTV:CAC).")
    ],
    11: [
        ("TITLE", "Snapshots of Prototype & Verification"),
        ("BOLD", "Verified Prototype Components:"),
        ("BULLET", "1. Desktop Command Center (gui_app.py): Tkinter GUI with Matte Titanium palette, 15 FPS capped rendering, multi-camera switching."),
        ("BULLET", "2. Web Surveillance Portal (web_server.py): Live console running on port 5000 with real-time occupancy and curfew rosters."),
        ("BULLET", "3. Automated Test Suite (test_suite.py): 10/10 tests passed successfully in 7.79 seconds."),
        ("BLANK", ""),
        ("BOLD", "Live Test Benchmarks:"),
        ("BULLET", "Face Match: 859.6ms (Confidence: 76.4%, Distance: 0.2355) | Forward Pass: 16.277ms | AES-256 Vector Cryptography: 100% verified.")
    ],
    12: [
        ("TITLE", "Prototype Performance Benchmarking"),
        ("BOLD", "Key Benchmarks:"),
        ("BULLET", "128-D Vector Match Speed: < 0.2 ms on standard quad-core CPU."),
        ("BULLET", "Inference Forward Pass: 16.2 ms (60+ FPS theoretical throughput)."),
        ("BULLET", "Dedicated GPU / VRAM Required: 0 MB (100% optimized for CPU instruction sets)."),
        ("BULLET", "Host CPU Utilization: 15% - 25% | RAM Working Set: ~450 MB (zero memory leaks)."),
        ("BLANK", ""),
        ("BOLD", "Token Cost Optimization vs Cloud Computer Vision:"),
        ("BULLET", "Naive Cloud Video Streaming to LLM: 27.8M tokens/hour/camera ($69.66/hr) = commercially unviable."),
        ("BULLET", "HawkVzon Architecture: 0 Tokens at edge + ~150 Tokens/day via Gemini 1.5 Flash = 99.999% Token Reduction.")
    ],
    13: [
        ("TITLE", "Roadmap & Google Ecosystem Synergy"),
        ("BOLD", "Phased Commercial Roadmap:"),
        ("BULLET", "Phase 1 (Months 1-3): Kota & Sikar beachhead - Onboard first 30 coaching hostels remotely. Refine ADMS stability."),
        ("BULLET", "Phase 2 (Months 4-6): ERP & Distributor Partnerships - Partner with top 3 regional CCTV distributors (30% rev-share)."),
        ("BULLET", "Phase 3 (Months 7-12): National Expansion - Scale to Hyderabad, Pune, Dehradun (250 hostels, Rs 1.08 Crores ARR)."),
        ("BLANK", ""),
        ("BOLD", "Google Ecosystem Integrations:"),
        ("BULLET", "Android Nearby Share / BLE: Instant student hostel beaconing upon walking into gate perimeter."),
        ("BULLET", "Google Cloud Firestore: Real-time multi-tenant database synchronization across warden mobile apps.")
    ]
}

def create_run(text, bold=False, sz=1400, color="202124"):
    r = ET.Element('{http://schemas.openxmlformats.org/drawingml/2006/main}r')
    rPr = ET.SubElement(r, '{http://schemas.openxmlformats.org/drawingml/2006/main}rPr')
    rPr.set('lang', 'en-GB')
    rPr.set('sz', str(sz))
    if bold:
        rPr.set('b', '1')
    
    solidFill = ET.SubElement(rPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}solidFill')
    srgbClr = ET.SubElement(solidFill, '{http://schemas.openxmlformats.org/drawingml/2006/main}srgbClr')
    srgbClr.set('val', color)

    latin = ET.SubElement(rPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}latin')
    latin.set('typeface', 'Google Sans Flex' if not bold else 'Google Sans Flex Medium')
    t = ET.SubElement(r, '{http://schemas.openxmlformats.org/drawingml/2006/main}t')
    t.text = text
    return r

def build_tx_body(items):
    txBody = ET.Element('{http://schemas.openxmlformats.org/presentationml/2006/main}txBody')
    bodyPr = ET.SubElement(txBody, '{http://schemas.openxmlformats.org/drawingml/2006/main}bodyPr')
    bodyPr.set('anchor', 't')
    bodyPr.set('wrap', 'square')
    bodyPr.set('lIns', '91425')
    bodyPr.set('tIns', '91425')
    bodyPr.set('rIns', '91425')
    bodyPr.set('bIns', '91425')
    spAutoFit = ET.SubElement(bodyPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}spAutoFit')
    lstStyle = ET.SubElement(txBody, '{http://schemas.openxmlformats.org/drawingml/2006/main}lstStyle')

    for item in items:
        kind = item[0]
        p = ET.SubElement(txBody, '{http://schemas.openxmlformats.org/drawingml/2006/main}p')
        pPr = ET.SubElement(p, '{http://schemas.openxmlformats.org/drawingml/2006/main}pPr')
        pPr.set('algn', 'l')
        
        spcBef = ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}spcBef')
        spcPts = ET.SubElement(spcBef, '{http://schemas.openxmlformats.org/drawingml/2006/main}spcPts')
        spcAft = ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}spcAft')
        spcPtsAft = ET.SubElement(spcAft, '{http://schemas.openxmlformats.org/drawingml/2006/main}spcPts')
        
        if kind == "TITLE":
            spcPts.set('val', '0')
            spcPtsAft.set('val', '80')
            ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}buNone')
            p.append(create_run(item[1], bold=True, sz=1800, color="1a73e8"))
        elif kind == "BOLD_FIELD":
            spcPts.set('val', '40')
            spcPtsAft.set('val', '40')
            ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}buNone')
            p.append(create_run(item[1], bold=True, sz=1300, color="202124"))
            p.append(create_run(item[2], bold=False, sz=1300, color="3c4043"))
        elif kind == "BOLD":
            spcPts.set('val', '50')
            spcPtsAft.set('val', '30')
            ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}buNone')
            p.append(create_run(item[1], bold=True, sz=1350, color="137333"))
        elif kind == "BULLET":
            pPr.set('marL', '285750')
            pPr.set('indent', '-285750')
            spcPts.set('val', '30')
            spcPtsAft.set('val', '30')
            buChar = ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}buChar')
            buChar.set('char', '•')
            p.append(create_run(item[1], bold=False, sz=1250, color="3c4043"))
        elif kind == "BLANK":
            spcPts.set('val', '40')
            spcPtsAft.set('val', '0')
            ET.SubElement(pPr, '{http://schemas.openxmlformats.org/drawingml/2006/main}buNone')
            p.append(create_run("", sz=600))
            
    return txBody

# Process PPTX
os.makedirs(r'c:\Users\Abhijeet\Desktop\face-emotion-project-paused-work\exports', exist_ok=True)
with zipfile.ZipFile(src_pptx, 'r') as zin, zipfile.ZipFile(dst_pptx, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        fname = item.filename
        raw_data = zin.read(fname)
        
        slide_num = None
        if fname.startswith('ppt/slides/slide') and fname.endswith('.xml'):
            num_str = ''.join(filter(str.isdigit, fname))
            if num_str:
                slide_num = int(num_str)
                
        if slide_num and slide_num in slides_data:
            tree = ET.fromstring(raw_data)
            sp_found = False
            for sp in tree.iter('{http://schemas.openxmlformats.org/presentationml/2006/main}sp'):
                xfrm = sp.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}xfrm')
                if xfrm is not None:
                    off = xfrm.find('{http://schemas.openxmlformats.org/drawingml/2006/main}off')
                    ext = xfrm.find('{http://schemas.openxmlformats.org/drawingml/2006/main}ext')
                    if off is not None and ext is not None:
                        off.set('x', '450000')
                        off.set('y', '950000')
                        ext.set('cx', '8244000')
                        ext.set('cy', '3900000')
                
                old_tx = sp.find('{http://schemas.openxmlformats.org/presentationml/2006/main}txBody')
                if old_tx is not None:
                    sp.remove(old_tx)
                new_tx = build_tx_body(slides_data[slide_num])
                sp.append(new_tx)
                sp_found = True
                break
                
            new_xml = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
            zout.writestr(fname, new_xml)
        else:
            zout.writestr(fname, raw_data)

print(f'Successfully generated {dst_pptx}!')
if os.path.exists(dst_pptx):
    print(f'Size: {os.path.getsize(dst_pptx) / 1024:.1f} KB')
