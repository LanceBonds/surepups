# main.py
import os
import subprocess
import tempfile
import zipfile
from typing import Literal
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Canine Cart Parametric CAD Engine", version="1.0.0")

# Enable CORS for frontend form integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCAD_TEMPLATE_PATH = os.getenv("SCAD_TEMPLATE_PATH", "./cad_templates/parametric_cart.scad")


class Measurements(BaseModel):
    heightFlankA: float = Field(..., description="Floor to flank fold height")
    lengthBodyB: float = Field(..., description="Shoulder to rump length")
    widthChestC: float = Field(..., description="Widest ribcage width")
    widthHipD: float = Field(..., description="Widest pelvic width")
    weightE: float = Field(..., description="Total body weight")


class CartOrderPayload(BaseModel):
    dogName: str
    units: Literal["in", "cm"]
    measurements: Measurements


def cleanup_temp_dir(temp_dir_path: str):
    """Deletes temporary rendering directory after file response delivery."""
    try:
        if os.path.exists(temp_dir_path):
            for root, dirs, files in os.walk(temp_dir_path, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(temp_dir_path)
    except Exception as e:
        print(f"Error cleaning up {temp_dir_path}: {e}")


def calculate_engineering_specs(m: Measurements, units: str):
    """Normalizes measurements to metric (mm/kg) and computes hardware sizing."""
    is_imperial = units == "in"
    scale_to_mm = 25.4 if is_imperial else 10.0
    scale_to_kg = 0.453592 if is_imperial else 1.0

    flank_h_mm = m.heightFlankA * scale_to_mm
    body_l_mm = m.lengthBodyB * scale_to_mm
    chest_w_mm = m.widthChestC * scale_to_mm
    hip_w_mm = m.widthHipD * scale_to_mm
    weight_kg = m.weightE * scale_to_kg

    # 1. Structural Tubing Sizing (6061 Aluminum)
    if weight_kg < 12.0:
        tube_od_mm = 12.7  # 0.50" OD
        wall_thk_mm = 1.2
        frame_class = "Toy"
        infill_pct = 35
    elif weight_kg <= 28.0:
        tube_od_mm = 19.05  # 0.75" OD
        wall_thk_mm = 1.65
        frame_class = "Standard"
        infill_pct = 50
    else:
        tube_od_mm = 25.4  # 1.00" OD
        wall_thk_mm = 2.1
        frame_class = "Heavy-Duty"
        infill_pct = 75

    # 2. Wheel Diameter Selection
    if flank_h_mm < 200:
        wheel_dia_mm = 100.0  # 4" Wheel
    elif flank_h_mm <= 380:
        wheel_dia_mm = 200.0  # 8" Wheel
    else:
        wheel_dia_mm = 300.0  # 12" Wheel

    # 3. Aluminum Cut Lengths (with mechanical offsets)
    side_rail_cut_mm = body_l_mm + 65.0
    crossbar_cut_mm = max(chest_w_mm, hip_w_mm) + 40.0
    strut_drop_cut_mm = max(60.0, flank_h_mm - (wheel_dia_mm / 2.0))

    return {
        "flank_h_mm": flank_h_mm,
        "body_l_mm": body_l_mm,
        "chest_w_mm": chest_w_mm,
        "hip_w_mm": hip_w_mm,
        "weight_kg": weight_kg,
        "tube_od_mm": tube_od_mm,
        "wall_thk_mm": wall_thk_mm,
        "wheel_dia_mm": wheel_dia_mm,
        "side_rail_cut_mm": side_rail_cut_mm,
        "crossbar_cut_mm": crossbar_cut_mm,
        "strut_drop_cut_mm": strut_drop_cut_mm,
        "frame_class": frame_class,
        "infill_pct": infill_pct,
    }


def render_openscad_part(output_path: str, part_name: str, params: dict):
    """Executes OpenSCAD CLI in headless mode to render a specific part."""
    cmd = [
        "openscad",
        "-o", output_path,
        "-D", f'PART_SELECTOR="{part_name}"',
        "-D", f'TUBE_OD={params["tube_od_mm"]}',
        "-D", f'HIP_WIDTH={params["hip_w_mm"]}',
        "-D", f'CHEST_WIDTH={params["chest_w_mm"]}',
        "-D", f'WHEEL_DIA={params["wheel_dia_mm"]}',
        "-D", f'STRUT_DROP={params["strut_drop_cut_mm"]}',
        SCAD_TEMPLATE_PATH
    ]
    
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"OpenSCAD render failed for {part_name}: {result.stderr}")


@app.post("/api/v1/generate-cart-package")
async def generate_cart_package(payload: CartOrderPayload, background_tasks: BackgroundTasks):
    specs = calculate_engineering_specs(payload.measurements, payload.units)

    temp_dir = tempfile.mkdtemp(prefix=f"cart_{payload.dogName.lower()}_")
    zip_filename = f"{payload.dogName}_cart_fabrication_kit.zip"
    zip_path = os.path.join(temp_dir, zip_filename)

    parts_to_render = [
        "rear_strut_mount_left",
        "rear_strut_mount_right",
        "hip_saddle_crossbar_clamp",
        "front_harness_clamp_left",
        "front_harness_clamp_right"
    ]

    generated_stl_files = []

    # 1. Headless OpenSCAD STL Generation
    for part in parts_to_render:
        stl_path = os.path.join(temp_dir, f"{part}.stl")
        try:
            render_openscad_part(stl_path, part, specs)
            generated_stl_files.append(stl_path)
        except Exception as e:
            cleanup_temp_dir(temp_dir)
            raise HTTPException(status_code=500, detail=str(e))

    # 2. Generate Aluminum Tubing Cut Sheet & Print Settings
    cut_sheet_path = os.path.join(temp_dir, "CUT_SHEET_AND_ASSEMBLY_BOM.txt")
    with open(cut_sheet_path, "w") as f:
        f.write(f"====================================================\n")
        f.write(f"FABRICATION & ASSEMBLY SPECIFICATION: {payload.dogName.upper()}\n")
        f.write(f"====================================================\n\n")
        f.write(f"Anatomical Inputs:\n")
        f.write(f"  - Flank Height: {payload.measurements.heightFlankA} {payload.units}\n")
        f.write(f"  - Body Length:  {payload.measurements.lengthBodyB} {payload.units}\n")
        f.write(f"  - Chest Width:  {payload.measurements.widthChestC} {payload.units}\n")
        f.write(f"  - Hip Width:    {payload.measurements.widthHipD} {payload.units}\n")
        f.write(f"  - Total Weight: {payload.measurements.weightE} {payload.units}\n\n")
        f.write(f"Frame Configuration:\n")
        f.write(f"  - Frame Class: {specs['frame_class']}\n")
        f.write(f"  - Tubing Spec: 6061-T6 Aluminum ({specs['tube_od_mm']:.2f}mm / {specs['tube_od_mm']/25.4:.2f}\" OD)\n")
        f.write(f"  - Wheel Spec:  {specs['wheel_dia_mm']:.0f}mm OD ({specs['wheel_dia_mm']/25.4:.0f}\" Diameter)\n\n")
        f.write(f"Aluminum Tubing Cut List (Qty x Length):\n")
        f.write(f"  [x2] Side Rails:       {specs['side_rail_cut_mm']:.1f} mm ({specs['side_rail_cut_mm']/25.4:.2f} in)\n")
        f.write(f"  [x1] Rear Crossbar:    {specs['crossbar_cut_mm']:.1f} mm ({specs['crossbar_cut_mm']/25.4:.2f} in)\n")
        f.write(f"  [x2] Wheel Strut Legs: {specs['strut_drop_cut_mm']:.1f} mm ({specs['strut_drop_cut_mm']/25.4:.2f} in)\n\n")
        f.write(f"3D Slicer Print Guidelines:\n")
        f.write(f"  - Material: PETG (Standard) or Polycarbonate / ABS (Heavy-Duty)\n")
        f.write(f"  - Recommended Infill: {specs['infill_pct']}%\n")
        f.write(f"  - Perimeters / Wall Loops: 4 minimum\n")
        f.write(f"====================================================\n")

    # 3. Bundle into Zip Archive
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_out:
        zip_out.write(cut_sheet_path, arcname=os.path.basename(cut_sheet_path))
        for stl in generated_stl_files:
            zip_out.write(stl, arcname=os.path.basename(stl))

    # Schedule folder cleanup after response is completed
    background_tasks.add_task(cleanup_temp_dir, temp_dir)

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_filename
    )