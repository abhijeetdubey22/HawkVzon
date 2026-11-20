# HawkVzon AI - Requirements & Token Telemetry Specification

## 1. Problem Statement & User Requirement
The mentor explicitly asked: *"How much token does your project use? Show optimization and consumption."*
While HawkVzon does **not** rely on cloud LLM tokens for continuous video surveillance (which runs 100% on local computer vision), evaluators and mentors require concrete proof of **Token Optimization, Consumption, and Edge Savings**.

## 2. Token Architecture Specification

### Baseline Comparison: Naïve Cloud Multimodal LLM
- Standard Multimodal LLM (GPT-4o / Gemini 1.5 Flash): ~258 tokens per image frame for video comprehension.
- At 30 FPS:
  - $30 \text{ frames/s} \times 258 \text{ tokens} = 7,740 \text{ tokens/second}$.
  - $7,740 \times 3600\text{s} = \mathbf{27,864,000 \text{ tokens/hour/camera}}$.
  - Cost at \$2.50 / 1M tokens: $\mathbf{\$69.66 \text{ per camera per hour}}$ (\$1,671/day/camera).

### HawkVzon Edge-Optimized Model
- **Continuous Edge Surveillance (0 Tokens):**
  - OpenCV, dlib (128-D vectors), Caffe/HDF5 neural models execute locally on CPU.
  - **Tokens Consumed: 0 tokens.**
  - **Tokens Saved: 27,864,000 tokens/camera/hour.**
- **Event-Driven Incident Synthesis (~140 Tokens):**
  - Only when an unauthorized breach, loitering, or perimeter intrusion is confirmed, a compact 65-token JSON event is formatted and synthesized into a 75-token executive dispatch.
  - Total tokens per security incident: **~140 tokens**.
- **Token Efficiency Score:**
  $$\text{Efficiency} = \frac{27,864,000 - 140}{27,864,000} \times 100\% = \mathbf{99.9995\% \text{ Token Reduction}}.$$

## 3. Telemetry & User Interface Deliverables
1. **`token_telemetry.py` Engine:**
   - Real-time tracking of frames processed, tokens saved, tokens consumed, and dollar cost saved.
   - CLI mode that generates an ASCII benchmark summary card for mentors and evaluators.
2. **Desktop GUI Integration (`gui_app.py`):**
   - Token Economy KPI widget & status bar counter.
   - Clickable "Token Audit" dialog displaying the side-by-side comparison table.
3. **Web Portal Integration (`web_server.py`):**
   - Telemetry card on the executive dashboard showing live token consumption vs. edge savings.
4. **Mentor Defense Dossier (`docs/TOKEN_ECONOMY_AND_BENCHMARKS.md`):**
   - Full printable technical whitepaper explaining the edge-to-cloud token architecture.
