import os

# Must be set before ctranslate2 / faster-whisper are imported.
# Prevents MKL's allocator from failing on Windows ("mkl_malloc: failed to allocate memory").
os.environ.setdefault("MKL_THREADING_LAYER", "GNU")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from app.main import main  # noqa: E402

if __name__ == "__main__":
    main()
