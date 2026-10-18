# Architecture Decision Records (ADR)

This document chronicles key architectural, infrastructure, and modeling decisions for the AI-Based Document Forgery Detection project.

---

### ADR-001: Project Scaffolding & Multi-Task Forgery Detection Architecture
* **Context:**  
  Document forgery detection (benchmarked on DocTamper and CASIA 2.0) requires handling both whole-document authenticity determination and fine-grained, pixel-level manipulation localization (e.g., altered financial figures, stamped signatures, spliced text, or erased clauses). In addition, uncompressed or uniformly re-compressed documents may bypass standard RGB convolutional filters. We need a modular, testable project scaffolding adapted from the proven Skin-Lesion pipeline capable of supporting three modeling paradigms: ResNet (classification), U-Net (segmentation), and Convolutional Autoencoder (anomaly reconstruction).

* **Decision:**  
  1. Adopt a modular layout separating data manifests (`data/processed/metadata.csv`), core PyTorch modules (`src/`), evaluation notebooks (`notebooks/`), and lightweight web serving (`flask_app/`).
  2. Standardize data ingestion to output unified tuples containing RGB image, ground-truth binary mask ($1 = \text{tampered}, 0 = \text{authentic}$), and Error Level Analysis (ELA) difference maps.
  3. Formulate the primary localization baseline using U-Net trained with a composite loss:
     $$\mathcal{L}_{total} = \alpha \mathcal{L}_{BCE} + (1 - \alpha) \mathcal{L}_{Dice}$$
     addressing severe class imbalance (often $< 5\%$ of document pixels are forged).
  4. Pin all dependencies strictly with upper bounds below breaking C-API changes (`numpy < 2.0.0`, `torch < 2.3.0`).

* **Alternatives Considered:**  
  * *Pure Classification (ResNet-only):* Rejected as primary model because identifying that a 10-page document is "tampered" without pinpointing the exact modified date or signature provides insufficient forensic utility.
  * *Pure Object Detection (YOLO/Faster R-CNN with bounding boxes):* Rejected because forged document elements (e.g., single-digit changes or pen strokes) have irregular, non-rectangular topological boundaries; bounding boxes introduce high background noise. Pixel-level masks via U-Net are mathematically superior.
  * *`torchvision.transforms.v2` over Albumentations:* Rejected because Albumentations offers higher CPU throughput on NumPy arrays and deterministic multi-target synchronization across image, mask, and ELA arrays.

* **Trade-offs & Constraints:**  
  * *Storage Overhead:* Generating and caching ELA images doubles disk footprint if precomputed. *Mitigation:* ELA will be computed on-the-fly during data loading in CPU worker threads ($O(H \times W)$ with small constant factor $< 15\text{ms}$ per $512 \times 512$ image).
  * *Mask Sparsity:* Forged regions occupy very few pixels, leading standard Cross-Entropy loss to converge to an all-zero trivial local minimum. *Mitigation:* Hard mining with Soft Dice Loss + Focal Loss weighting.

* **Failure Modes & Mitigations:**  
  * *Double Compression Artifacts:* If an authentic document is re-saved before inference, naive ELA may flag uniform high-frequency grids. *Mitigation:* Train models on both raw uncompressed and re-compressed authentic samples, and use dual-branch RGB + ELA feature fusion rather than ELA alone.
  * *Resolution Downsampling Distortion:* Downscaling high-resolution scanned documents ($3000 \times 2000$) directly to $256 \times 256$ destroys fine text tampering. *Mitigation:* Ingestion pipeline will support overlapping patch extraction ($512 \times 512$ sliding window with stride 256) during inference.
