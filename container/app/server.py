"""Bounded HTTP boundary for the native renderer container."""

from email.parser import BytesParser
from email.policy import default
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

from PIL import Image

from .extractor import extract_scene_graph
from .renderer import RenderError, render_scene
from .schemas import SceneGraphError, validate_scene_graph
from .validator import validate_fidelity


MAX_REFERENCE_BYTES = 20 * 1024 * 1024
MAX_SCENE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_REFERENCE_BYTES + MAX_SCENE_BYTES + 1024 * 1024
MAX_DEBUG_PREVIEW_BYTES = 64 * 1024


def _diagnostic_preview(path):
    with Image.open(path) as source:
        image = source.convert("RGB")
    for maximum, quality in ((720, 60), (540, 45), (360, 30), (240, 20)):
        candidate = image.copy()
        candidate.thumbnail((maximum, maximum))
        output = io.BytesIO()
        candidate.save(output, "JPEG", quality=quality, optimize=True)
        payload = output.getvalue()
        if len(payload) <= MAX_DEBUG_PREVIEW_BYTES:
            return payload
    raise RenderRequestError(
        "DEBUG_PREVIEW_TOO_LARGE",
        "diagnostic preview could not be bounded",
        500,
    )


class RenderRequestError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.status = status


class FidelityValidationError(RenderRequestError):
    def __init__(self, report, preview_bytes):
        super().__init__(
            "FIDELITY_FAILED",
            "Generated DOCX failed independent fidelity validation",
            422,
        )
        self.report = report
        self.preview_bytes = preview_bytes


def render_request(scene_bytes, reference_name, reference_bytes, workspace):
    """Validate one request and return an in-memory ZIP result."""

    if len(scene_bytes) > MAX_SCENE_BYTES or len(reference_bytes) > MAX_REFERENCE_BYTES:
        raise RenderRequestError("REQUEST_TOO_LARGE", "render input exceeds its byte limit", 413)
    if not reference_bytes:
        raise RenderRequestError("REFERENCE_EMPTY", "reference file is empty")
    try:
        scene_value = json.loads(scene_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RenderRequestError("SCENE_JSON", "scene is not valid UTF-8 JSON") from error
    try:
        scene = validate_scene_graph(scene_value)
    except SceneGraphError as error:
        raise RenderRequestError(error.code, str(error)) from error

    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    suffix = Path(reference_name or "reference.bin").suffix.lower() or ".bin"
    reference_path = workspace / ("reference%s" % suffix)
    reference_path.write_bytes(reference_bytes)
    artifact = render_scene(scene, reference_path, workspace)
    report = validate_fidelity(
        reference_path, artifact.png_path, scene, artifact.manifest
    )
    if report["status"] != "PASS":
        raise FidelityValidationError(report, _diagnostic_preview(artifact.png_path))
    manifest = dict(artifact.manifest)
    manifest["fidelity"] = report

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(artifact.docx_path, "artifact.docx")
        archive.write(artifact.pdf_path, "artifact.pdf")
        archive.write(artifact.png_path, "artifact.png")
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        )
    return output.getvalue()


def extract_render_request(reference_name, reference_bytes, hints_bytes, workspace):
    """Deterministically measure, render, and validate one reference."""

    if len(reference_bytes) > MAX_REFERENCE_BYTES:
        raise RenderRequestError("REQUEST_TOO_LARGE", "reference exceeds its byte limit", 413)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    suffix = Path(reference_name or "reference.bin").suffix.lower() or ".bin"
    reference_path = workspace / ("reference%s" % suffix)
    reference_path.write_bytes(reference_bytes)
    try:
        hints = json.loads((hints_bytes or b"{}").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RenderRequestError("HINTS_JSON", "hints are not valid UTF-8 JSON") from error
    scene = extract_scene_graph(reference_path, hints)
    return render_request(
        json.dumps(scene, separators=(",", ":")).encode("utf-8"),
        reference_path.name,
        reference_bytes,
        workspace,
    )


def _multipart_parts(content_type, body):
    if not content_type.lower().startswith("multipart/form-data"):
        raise RenderRequestError("REQUEST_MEDIA_TYPE", "multipart/form-data is required", 415)
    envelope = (
        b"Content-Type: "
        + content_type.encode("ascii", "strict")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + body
    )
    message = BytesParser(policy=default).parsebytes(envelope)
    if not message.is_multipart():
        raise RenderRequestError("REQUEST_MULTIPART", "multipart body is malformed")
    parts = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if name:
            parts[name] = {
                "filename": part.get_filename(),
                "payload": part.get_payload(decode=True) or b"",
            }
    return parts


class RenderHandler(BaseHTTPRequestHandler):
    server_version = "ArtifactMimicryRenderer/1"

    def _json(self, status, value):
        payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path != "/health":
            self._json(404, {"status": "NOT_FOUND"})
            return
        self._json(200, {"status": "ok"})

    def do_POST(self):
        if self.path not in {"/render", "/extract-render"}:
            self._json(404, {"status": "NOT_FOUND"})
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise RenderRequestError(
                    "REQUEST_TOO_LARGE", "request length is absent or outside limits", 413
                )
            body = self.rfile.read(length)
            parts = _multipart_parts(self.headers.get("content-type", ""), body)
            if "reference" not in parts or (
                self.path == "/render" and "scene" not in parts
            ):
                raise RenderRequestError(
                    "REQUEST_PARTS", "required multipart fields are missing"
                )
            with tempfile.TemporaryDirectory(prefix="artifact-mimicry-") as directory:
                if self.path == "/extract-render":
                    result = extract_render_request(
                        parts["reference"]["filename"] or "reference.bin",
                        parts["reference"]["payload"],
                        parts.get("hints", {}).get("payload", b"{}"),
                        Path(directory),
                    )
                else:
                    result = render_request(
                        parts["scene"]["payload"],
                        parts["reference"]["filename"] or "reference.bin",
                        parts["reference"]["payload"],
                        Path(directory),
                    )
            self.send_response(200)
            self.send_header("content-type", "application/zip")
            self.send_header("content-length", str(len(result)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(result)
        except RenderRequestError as error:
            response = {
                "status": "FAIL",
                "code": error.code,
                "message": str(error),
            }
            if isinstance(error, FidelityValidationError):
                response["validation"] = error.report
                response["debug_preview_base64"] = base64.b64encode(
                    error.preview_bytes
                ).decode("ascii")
                response["debug_preview_mime"] = "image/jpeg"
            self._json(
                error.status,
                response,
            )
        except RenderError as error:
            self._json(
                422,
                {"status": "FAIL", "code": "RENDER_FAILED", "message": str(error)},
            )
        except Exception:
            self._json(
                500,
                {
                    "status": "FAIL",
                    "code": "RENDERER_UNAVAILABLE",
                    "message": "Native renderer unavailable. No artifact was generated.",
                },
            )

    def log_message(self, format, *args):
        return


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), RenderHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
