import base64
import io
import os
import cv2
import numpy as np
import torch
import torchvision.transforms.functional as TF
from flask import Flask, render_template, request, jsonify
from PIL import Image
import segmentation_models_pytorch as smp

app = Flask(__name__)

# --- Configuration & Calibration Constants ---
OPTIMAL_THRESHOLD = 0.60   # Calibrated optimal decision boundary from Notebook 03
MIN_FORGERY_PIXELS = 50    # Minimum pixel count to flag a document as tampered

# Exact path based on repository layout: DocForgery/models/checkpoints/best_unet.pth
CHECKPOINT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "models", "checkpoints", "best_unet.pth")
)

device = torch.device("cpu")

# --- Model Loading ---
print(f"[*] Initializing U-Net (ResNet-34 backbone)...")
model = smp.Unet(
    encoder_name="resnet34",
    encoder_weights=None,
    in_channels=3,
    classes=1
)

if not os.path.exists(CHECKPOINT_PATH):
    raise FileNotFoundError(
        f"Checkpoint missing at: {CHECKPOINT_PATH}\n"
        f"Please verify best_unet.pth is inside models/checkpoints/"
    )

print(f"[*] Loading model weights from: {CHECKPOINT_PATH}")
model.load_state_dict(torch.load(CHECKPOINT_PATH, map_location=device))
model.to(device)
model.eval()
print("[*] Model successfully loaded on CPU and ready for inference.\n")


def preprocess_image(pil_img: Image.Image) -> torch.Tensor:
    """Applies exact training transforms: 256x256 resize + ImageNet normalization."""
    resized = TF.resize(pil_img, (256, 256), interpolation=TF.InterpolationMode.BILINEAR)
    img_tensor = TF.to_tensor(resized)
    img_tensor = TF.normalize(img_tensor, mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    return img_tensor.unsqueeze(0).to(device)


def pil_to_base64(pil_img: Image.Image) -> str:
    """Encodes a PIL Image into an in-memory base64 data URI string."""
    buffered = io.BytesIO()
    pil_img.save(buffered, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode("utf-8")


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/predict", methods=["POST"])
def predict():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename provided."}), 400

    try:
        # 1. Load uploaded image and record native dimensions
        original_img = Image.open(file.stream).convert("RGB")
        orig_w, orig_h = original_img.size
        orig_np = np.array(original_img)

        # 2. Run Forward Inference
        input_tensor = preprocess_image(original_img)
        with torch.no_grad():
            logits = model(input_tensor)
            prob_map_256 = torch.sigmoid(logits)[0, 0].cpu().numpy()

        # 3. Rescale probability heatmap back to original resolution
        prob_map_orig = cv2.resize(prob_map_256, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
        binary_mask_orig = (prob_map_orig > OPTIMAL_THRESHOLD).astype(np.uint8)

        # 4. Compute Quantitative Forgery Metrics
        forged_pixels = int(np.sum(binary_mask_orig > 0))
        total_pixels = orig_w * orig_h
        forged_area_pct = (forged_pixels / total_pixels) * 100.0
        max_confidence = float(np.max(prob_map_orig))

        is_tampered = forged_pixels >= MIN_FORGERY_PIXELS
        verdict = "Tampered Document" if is_tampered else "Authentic / Clean"

        # 5. Build Visual Highlights
        overlay_np = orig_np.copy()
        overlay_np[binary_mask_orig > 0] = [255, 30, 30]  # Red highlight on forged regions
        blended_np = cv2.addWeighted(orig_np, 0.70, overlay_np, 0.30, 0)

        mask_display_np = (binary_mask_orig * 255).astype(np.uint8)

        # 6. Encode outputs to Base64 (zero server-side disk clutter)
        orig_b64 = pil_to_base64(original_img)
        overlay_b64 = pil_to_base64(Image.fromarray(blended_np))
        mask_b64 = pil_to_base64(Image.fromarray(mask_display_np))

        return jsonify({
            "verdict": verdict,
            "is_tampered": is_tampered,
            "forged_area_pct": round(forged_area_pct, 2),
            "max_confidence": round(max_confidence, 2),
            "orig_image": orig_b64,
            "overlay_image": overlay_b64,
            "mask_image": mask_b64,
            "threshold_used": OPTIMAL_THRESHOLD
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)