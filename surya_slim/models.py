from dataclasses import dataclass


@dataclass(slots=True)
class BlockOCRResult:
    polygon: list[list[float]]
    label: str
    raw_label: str
    reading_order: int
    html: str = ""
    skipped: bool = False
    error: bool = False

    @property
    def bbox(self) -> list[float]:
        x_coordinates = [point[0] for point in self.polygon]
        y_coordinates = [point[1] for point in self.polygon]
        return [
            min(x_coordinates),
            min(y_coordinates),
            max(x_coordinates),
            max(y_coordinates),
        ]


@dataclass(slots=True)
class PageOCRResult:
    blocks: list[BlockOCRResult]
    image_bbox: list[float]
    confidence: float | None = None
