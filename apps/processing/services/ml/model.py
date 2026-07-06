"""U-Net liviano para segmentación semántica de planos arquitectónicos.

Arquitectura:
- 4 niveles de profundidad (64→128→256→512)
- Doble conv + BatchNorm + ReLU por nivel
- Skip connections (concatenación)
- Salida: 5 canales (fondo, pared, puerta, mueble, vano)

Entrenado con supervisión: imágenes de croquis → máscaras de
segmentación pixel-level.  En inferencia produce una máscara
por clase que luego se vectoriza con LSD + post-procesado.

La carga del modelo es lazy (solo se carga a RAM cuando se
invoca por primera vez).  El modelo entrenado se guarda en
media/models/unet_segmentation.pt
"""

import logging
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)

N_CLASSES = 5
CLASS_NAMES = ['fondo', 'pared', 'puerta', 'mueble', 'vano']


class DoubleConv(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.conv(x)


class Down(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.pool = nn.MaxPool2d(2)
        self.conv = DoubleConv(in_ch, out_ch)

    def forward(self, x):
        return self.conv(self.pool(x))


class Up(nn.Module):
    def __init__(self, in_ch, out_ch, bilinear=True):
        super().__init__()
        if bilinear:
            self.up = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
            self.conv = DoubleConv(in_ch, out_ch)
        else:
            self.up = nn.ConvTranspose2d(in_ch, in_ch // 2, 2, stride=2)
            self.conv = DoubleConv(in_ch, out_ch)

    def forward(self, x1, x2):
        x1 = self.up(x1)
        diff_y = x2.size(2) - x1.size(2)
        diff_x = x2.size(3) - x1.size(3)
        x1 = F.pad(x1, [diff_x // 2, diff_x - diff_x // 2,
                        diff_y // 2, diff_y - diff_y // 2])
        x = torch.cat([x2, x1], dim=1)
        return self.conv(x)


class UNet(nn.Module):
    """U-Net para segmentación de planos arquitectónicos.

    Args:
        n_channels: canales de entrada (default 3 para RGB)
        n_classes: canales de salida (default 5: fondo, pared, puerta, mueble, vano)
        base_filters: filtros base (default 64)
    """

    def __init__(self, n_channels=3, n_classes=N_CLASSES, base_filters=64):
        super().__init__()
        self.inc = DoubleConv(n_channels, base_filters)
        self.down1 = Down(base_filters, base_filters * 2)
        self.down2 = Down(base_filters * 2, base_filters * 4)
        self.down3 = Down(base_filters * 4, base_filters * 8)
        self.down4 = Down(base_filters * 8, base_filters * 8)
        self.up1 = Up(base_filters * 16, base_filters * 4)
        self.up2 = Up(base_filters * 8, base_filters * 2)
        self.up3 = Up(base_filters * 4, base_filters)
        self.up4 = Up(base_filters * 2, base_filters)
        self.outc = nn.Conv2d(base_filters, n_classes, 1)

    def forward(self, x):
        x1 = self.inc(x)
        x2 = self.down1(x1)
        x3 = self.down2(x2)
        x4 = self.down3(x3)
        x5 = self.down4(x4)
        x = self.up1(x5, x4)
        x = self.up2(x, x3)
        x = self.up3(x, x2)
        x = self.up4(x, x1)
        return self.outc(x)


class UNetSegmenter:
    """Wrapper de inferencia para el U-Net.

    Uso:
        segmenter = UNetSegmenter()
        segmenter.load('ruta/al/modelo.pt')
        masks = segmenter.predict(image_bgr)
        # masks['pared'] → máscara binaria numpy (H, W)
    """

    def __init__(self, model_path=None, device=None):
        self.device = device or torch.device('cpu')
        self.model = None
        self.model_path = Path(model_path) if model_path else None

    def load(self, model_path=None):
        if model_path:
            self.model_path = Path(model_path)
        if self.model_path is None or not self.model_path.exists():
            logger.warning('Modelo no encontrado en %s', self.model_path)
            return False
        try:
            self.model = UNet().to(self.device)
            state = torch.load(self.model_path, map_location=self.device, weights_only=True)
            if 'model_state_dict' in state:
                self.model.load_state_dict(state['model_state_dict'])
            else:
                self.model.load_state_dict(state)
            self.model.eval()
            logger.info('Modelo U-Net cargado desde %s', self.model_path)
            return True
        except Exception as e:
            logger.exception('Error al cargar modelo U-Net: %s', e)
            self.model = None
            return False

    def is_loaded(self):
        return self.model is not None

    @torch.no_grad()
    def predict(self, bgr_image):
        """Segmenta una imagen BGR.

        Args:
            bgr_image: numpy array (H, W, 3) en BGR

        Returns:
            dict: {class_name: máscara binaria numpy (H, W)}
        """
        if self.model is None:
            logger.warning('Modelo no cargado, no se puede segmentar')
            return {}

        h, w = bgr_image.shape[:2]

        # BGR → RGB, normalizar, añadir batch dim
        rgb = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB)
        tensor = torch.from_numpy(rgb).float().permute(2, 0, 1).unsqueeze(0)
        tensor = tensor / 127.5 - 1.0  # normalizar a [-1, 1]
        tensor = tensor.to(self.device)

        logits = self.model(tensor)
        pred = torch.argmax(logits, dim=1).squeeze(0).cpu().numpy().astype(np.uint8)

        masks = {}
        for i, name in enumerate(CLASS_NAMES):
            masks[name] = (pred == i).astype(np.uint8) * 255

        return masks


# Singleton para reutilizar el modelo en el pipeline
_segmenter_instance = None


def get_segmenter(model_path=None):
    global _segmenter_instance
    if _segmenter_instance is None:
        _segmenter_instance = UNetSegmenter(model_path)
    if model_path and not _segmenter_instance.is_loaded():
        _segmenter_instance.load(model_path)
    return _segmenter_instance
