"""Download/check the configured pose model locally; never upload video."""

from yolo_processor import YoloProcessor

if __name__ == "__main__":
    processor = YoloProcessor()
    processor.load()
    processor.close()
    if processor.state != "ready":
        raise SystemExit(1)
