# Product Requirements Document (PRD)

# Project: HawkVzon HostelOS — Full-Stack Cloud Biometric Middleware & Safety Platform

---

## Document Control & Executive Metadata
- **Product Name:** HawkVzon HostelOS (The Definitive V7.0 Blueprint)
- **Document Version:** 7.0 (Direct ADMS Cloud-Push & Full-Stack Hostel Baseline)
- **Target Market:** 8,000 Organized Coaching Hostels & Residential K-12 Boarding Schools (Kota, Sikar, Hyderabad, Pune, Dehradun)
- **Product Nature:** Cloud Webhook & Direct ADMS Biometric Terminal Processor (Zero Local PCs, Zero Door Relays, Zero Custom Hardware)
- **Pricing & Business Model:** Tiered **₹30/occupied bed/month** (₹3,600/month or **₹43,200/year** for an average 120-bed hostel, billed annually upfront) + **₹10,000** one-time remote ADMS setup
- **Unit Economics:** CAC: ₹15,000 | LTV: ₹1,14,696 | **LTV:CAC Ratio: 7.6:1** | **Gross Margin: 88.5%**
- **Meta WhatsApp Economics:** ₹0.1150/delivered utility template | 1-alert/day cap | Under **₹4,968/year** in Meta charges per hostel
- **AI Architecture:** Real-Time Local/Edge Matching (0 Tokens) + Google Gemini 1.5 Flash Nightly Curfew & Occupancy Digest (~150 Tokens)
- **Author:** Abhijeet Dubey (Lead AI Architect) & Antigravity Engineering
- **Status:** Approved / Commercial & Google Hackathon Master Baseline
- **Date:** November 2026

---

## 1. Executive Summary & The V7.0 Breakthrough

### 1.1 The Strategic Shift (Post-V6.0 Evolution)
HawkVzon v7.0 solves the two remaining vulnerabilities of previous versions:
1. **Eliminated the Local Reception Windows PC:** Direct ADMS (Automated Data Master System) Cloud-Push—eSSL and Matrix terminals send outbound HTTP/HTTPS POST events straight to your cloud backend over Wi-Fi/Ethernet with **zero local PC in between**.
2. **Defeated the ₹99/mo PG App Pricing Pressure:** Generic PG software (RentOk, My PG Manager) sells for ₹99/month, making a ₹48,000 alert-only tool look overpriced. HawkVzon v7.0 bundles:
   - Direct ADMS Hardware-Sync & 1-Ping/Day WhatsApp "Safe Evening Return" Alerts.
   - Parent-Approved Digital Out-Pass & Weekend Leave Workflow.
   - Automated UPI Rent / Hostel Fee Reminders.

| Metric | Previous Hardware Models (NO) | HawkVzon HostelOS v7.0 (YES!) |
| :--- | :--- | :--- |
| **Product Nature** | Custom hardware box + door relay | Cloud Webhook & Direct ADMS Terminal Processor |
| **Local PC Needed** | Yes (local PC crashes, port blocks) | **ZERO Local PC** (Terminals push direct to Cloud) |
| **Feature Set** | Alert notifications only | Full-Stack: Biometric Sync + Out-Passes + UPI Rent |
| **Pricing Model** | ₹1.2L upfront capex | **₹30 / bed / month** (₹43,200/yr for 120 beds) |
| **WhatsApp Message Cost** | Uncapped (erodes margin) | **1-Alert/Day Cap** (Meta cost < ₹4,968/year) |
| **Unit Economics** | LTV:CAC 1.3:1 (Bleeding cash) | **LTV:CAC 7.6:1** (World-Class SaaS, 88% Margin) |
| **Onboarding Speed** | 2 days on-site electrician | **30 minutes remote** keypad configuration |

---

## 2. Market Sizing & Competitive Defense

### 2.1 The ₹34.56 Crore Addressable Market
- 3,500 residential boarding schools + 4,500 organized coaching hostels = **8,000 facilities**.
- Average Hostel Size: 120 beds @ ₹30/bed/month = **₹43,200/year**.
- Total Addressable Market (TAM): 8,000 * ₹43,200 = **₹34.56 Crores / year**.
- Capturing 1,500 hostels across Kota, Sikar, and Hyderabad = **₹6.5 Crores in high-margin ARR** (88% gross margin) with a lean 10-person remote team.

---

## 3. Direct ADMS Cloud-Push Architecture

```
[Existing ₹12,000 eSSL / Matrix Terminal at Gate]
                         │
                         ▼ (Direct Outbound HTTP POST via Wi-Fi/LAN - ADMS Protocol)
[HawkVzon Cloud Ingestion Endpoint (/api/adms/push)]
                         │
                         ├─► Redis Rate-Limiter (Hard 1-Alert/Day Cap & 6-hr Cooldown)
                         ├─► Parent-Approved Digital Out-Pass Workflow
                         ├─► Automated UPI Rent Reminders (1st, 5th, 7th)
                         ├─► 09:30 PM Night Curfew Radar (web_server.py :5000)
                         └─► 10:00 PM Google Gemini 1.5 Flash Nightly Briefing (~150 Tokens)
```

---

## 4. Meta WhatsApp Utility Unit Economics (Hard Numbers)

Under Meta’s October 1, 2026 India pricing, utility templates cost **₹0.1150 per delivered message**. HawkVzon enforces strict **Anti-Spam Rate-Limiting**:

```
┌──────────────────────────────────────┬──────────────────────────────────────────┐
│ Parameter                            │ Production Value                         │
├──────────────────────────────────────┼──────────────────────────────────────────┤
│ Standard Hostel Capacity             │ 120 Beds                                 │
│ Rate-Limit Policy                    │ 1 "Safe Return" Ping/Day + 6-hr Cooldown │
│ Monthly WhatsApp Utility Messages    │ 120 students × 30 days = 3,600 messages  │
│ Cost per Delivered Utility Message   │ ₹0.1150 (Meta India Utility Rate)        │
│ Total Monthly Meta API Cost / Hostel │ 3,600 × ₹0.1150 = ₹414.00 / month        │
│ Total Annual Meta API Cost / Hostel  │ ₹414 × 12 = ₹4,968.00 / year             │
│ Annual Software Contract Realization │ ₹43,200.00 / year (Billed Upfront)       │
│ Cloud Hosting (AWS/GCP) per Tenant   │ ₹1,200.00 / year                         │
│ Software Gross Margin                │ 85.7% (Pure Software Gross Margin)       │
└──────────────────────────────────────┴──────────────────────────────────────────┘
```

---

## 5. Functional Requirements (FR)

### FR-1: Direct ADMS HTTP Push Receiver
- Cloud REST webhook `/iclock/cdata` and `/api/adms/push` parsing standard IClock/ADMS protocol packets transmitted by eSSL and Matrix devices.
- Device sends biometric user ID, device SN, timestamp, and in/out state over port 80/443. Ingestion latency < 200 ms.

### FR-2: 1-Alert-per-Day Rate Limiting & Cooldown Engine
- Prevents message spam when students repeatedly punch at the turnstile.
- Enforces a 6-hour punch cooldown per student. The system dispatches exactly **one "Safe Evening Return" WhatsApp notification** per day (triggered on the student's return from coaching, between 05:00 PM and 09:30 PM).

### FR-3: Parent-Approved Digital Out-Pass Engine
- Replaces handwritten paper out-pass registers for weekend leaves and medical outings.
- Student submits digital leave request on mobile web -> WhatsApp interactive button sent to parent: *“Approve weekend out-pass for Abhijeet? [Approve] [Reject]”* -> Turnstile unlatches on biometric punch *only* if the parent has clicked [Approve].

### FR-4: 09:30 PM Curfew Reconciliation & Warden Console
- Real-time visual hostel occupancy radar.
- At 09:31 PM, any enrolled student lacking a verified return punch and lacking an approved out-pass is flagged on the Warden’s mobile web console (`web_server.py :5000`).
- Automated WhatsApp check sent directly to the student's phone asking for location check-in before escalating to parents.

### FR-5: Automated UPI Rent & Hostel Fee Reminders
- Automatically sends WhatsApp reminders with embedded UPI payment links (Razorpay/Cashfree) on the 1st, 5th, and 7th of every month.

### FR-6: Google Gemini 10:00 PM Executive Safety Digest
- Emits a ~150-token JSON telemetry payload to **Google Gemini 1.5 Flash** at 10:00 PM, generating a natural-language curfew compliance summary for the hostel director.

### FR-7: Cryptographic Privacy & DPDP Compliance
- Zero raw photos stored in cloud. Biometric IDs are mapped to random UUIDs; student records are encrypted at rest under AES-256 with HMAC-SHA256 signatures.

---

## 6. Non-Functional Requirements (NFR)

### NFR-1: Remote Setup & Zero On-Site Visits
- Device configuration completed in < 30 minutes over a guided phone/WhatsApp video call with the hostel operator entering the cloud IP/Port on the terminal keypad.
- Zero local software to install; runs 100% on cloud serverless/VM infrastructure.

### NFR-2: Low Latency & High Message Deliverability
- Turnstile punch to WhatsApp parent delivery latency: <= 3 seconds.
- 99.8% message delivery SLA via Meta WhatsApp Business Cloud API.

### NFR-3: High Gross Margins
- COGS capped at <= 15% of annual contract value. Gross Margin maintained above **85%**.

---

## 7. Unit Economics & Capital Math (The 7.6:1 LTV:CAC Engine)

| Commercial Metric | HawkVzon HostelOS v7.0 Unit Economics |
| :--- | :--- |
| **Average Hostel Capacity** | 120 Beds |
| **Subscription Pricing** | ₹30 / bed / month |
| **Annual Contract Value (ACV)** | ₹43,200 / hostel / year (Billed Upfront) |
| **One-Time Remote ADMS Setup Fee** | ₹10,000 (Keypad setup & Meta onboarding) |
| **Year 1 Revenue per Client** | ₹53,200 |
| **Customer Acquisition Cost (CAC)** | ₹15,000 (Targeted remote inside sales) |
| **Annual Meta API & Cloud Hosting COGS** | ₹6,168 / year |
| **Annual Gross Profit per Client** | ₹37,032 / year |
| **Average Client Lifetime** | 3.5 Years |
| **Lifetime Value (LTV - Gross Profit)** | ₹1,14,696 |
| **LTV : CAC Ratio** | **7.6 : 1** (World-Class SaaS Unit Economics) |
| **Breakeven Runway** | **25 Hostels** (Achievable in 6 months) |

---

## 8. Verification & Success Metrics

1. **Remote Setup Speed:** <= 30 minutes keypad configuration time.
2. **Delivery Latency:** <= 3 seconds from turnstile punch to parent WhatsApp delivery.
3. **Margin Enforcement:** Total Meta utility message cost per hostel stays <= ₹4,968/year.
4. **Renewal Rate:** >= 88% annual renewal rate due to workflow ownership of out-passes and rent collections.
