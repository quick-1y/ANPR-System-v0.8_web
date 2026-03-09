from __future__ import annotations

from typing import Dict, Iterable, List, Tuple
import logging

import numpy as np
import torch
import torch.ao.quantization.quantize_fx as quantize_fx
from torch.ao.quantization import QConfigMapping
from torchvision import transforms

from packages.anpr_core.config import ANPRConfig
from packages.anpr_core.recognition.crnn import CRNN

logger = logging.getLogger(__name__)


class CRNNRecognizer:
    def __init__(self, config: ANPRConfig) -> None:
        target_device = config.device
        if target_device.type != "cpu":
            logger.warning("Квантованная OCR-модель поддерживает только CPU. Переключаемся на CPU вместо %s.", target_device)
            target_device = torch.device("cpu")

        self.device = target_device
        self.transform = transforms.Compose(
            [
                transforms.ToPILImage(),
                transforms.Grayscale(),
                transforms.Resize((config.ocr_height, config.ocr_width)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.5], std=[0.5]),
            ]
        )
        self.int_to_char: Dict[int, str] = {i + 1: char for i, char in enumerate(config.ocr_alphabet)}
        self.int_to_char[0] = ""
        model_to_load = CRNN(len(config.ocr_alphabet) + 1).eval()
        qconfig_mapping = QConfigMapping().set_global(torch.ao.quantization.get_default_qconfig("fbgemm"))
        example_inputs = (torch.randn(1, 1, config.ocr_height, config.ocr_width),)
        model_prepared = quantize_fx.prepare_fx(model_to_load, qconfig_mapping, example_inputs)
        model_quantized = quantize_fx.convert_fx(model_prepared)
        model_quantized.load_state_dict(torch.load(config.ocr_model_path, map_location=self.device))
        self.model = model_quantized.to(self.device)

    @torch.no_grad()
    def recognize_batch(self, plate_images: Iterable[np.ndarray]) -> List[Tuple[str, float]]:
        plate_images = list(plate_images)
        if not plate_images:
            return []
        batch = torch.stack([self.transform(img) for img in plate_images]).to(self.device)
        return self._decode_batch(self.model(batch))

    @torch.no_grad()
    def recognize(self, plate_image) -> Tuple[str, float]:
        result = self.recognize_batch([plate_image])
        return result[0] if result else ("", 0.0)

    def _decode_batch(self, log_probs: torch.Tensor) -> List[Tuple[str, float]]:
        batch_probs = log_probs.permute(1, 0, 2)
        results: List[Tuple[str, float]] = []
        for probs in batch_probs:
            decoded_chars: List[str] = []
            char_confidences: List[float] = []
            last_char_idx = 0
            for timestep_log_probs in probs:
                char_idx = int(torch.argmax(timestep_log_probs).item())
                char_conf = float(torch.exp(torch.max(timestep_log_probs)).item())
                if char_idx != 0 and char_idx != last_char_idx:
                    decoded_chars.append(self.int_to_char.get(char_idx, ""))
                    char_confidences.append(char_conf)
                last_char_idx = char_idx
            text = "".join(decoded_chars)
            results.append((text, (sum(char_confidences) / len(char_confidences)) if char_confidences else 0.0))
        return results
