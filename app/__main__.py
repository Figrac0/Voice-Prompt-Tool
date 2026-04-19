import os
import sys
from pathlib import Path

# Load .env from project root before anything else (sets GROQ_API_KEY etc.)
try:
    from dotenv import load_dotenv
    _root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    load_dotenv(_root / ".env")
except ImportError:
    pass

# Must be set before ctranslate2 / faster-whisper are imported.
# Prevents MKL's allocator from failing on Windows ("mkl_malloc: failed to allocate memory").
os.environ.setdefault("MKL_THREADING_LAYER", "GNU")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from app.main import main  # noqa: E402

if __name__ == "__main__":
    main()
