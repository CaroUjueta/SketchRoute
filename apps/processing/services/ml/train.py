"""Script de entrenamiento para el U-Net de segmentación de planos.

Uso:
    python -m apps.processing.services.ml.train \
        --data-dir /ruta/a/dataset \
        --epochs 100 \
        --batch-size 8 \
        --lr 1e-3

Estructura esperada del dataset:
    dataset/
        images/          # imágenes de croquis (RGB, cualquier tamaño)
            img001.png
            img002.png
            ...
        masks/           # máscaras PNG con índices de clase (0-4)
            img001.png   # fondo=0, pared=1, puerta=2, mueble=3, vano=4
            img002.png
            ...

Para generar dataset sintético desde el pipeline actual:
    python -m apps.processing.services.ml.train --generate-synthetic
"""

import argparse
import logging
import random
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torch.utils.tensorboard import SummaryWriter

from .model import UNet, N_CLASSES, CLASS_NAMES

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


class FloorPlanDataset(Dataset):
    """Dataset de planos arquitectónicos para segmentación."""

    def __init__(self, image_dir, mask_dir, img_size=(512, 512), augment=False):
        self.image_paths = sorted(Path(image_dir).glob('*'))
        self.mask_paths = sorted(Path(mask_dir).glob('*'))
        self.img_size = img_size
        self.augment = augment

        # filtrar imágenes sin máscara correspondiente
        valid = []
        for img_p in self.image_paths:
            mask_p = self.mask_paths / img_p.name
            if mask_p.exists():
                valid.append((str(img_p), str(mask_p)))
        self.samples = valid
        logger.info('Dataset: %d muestras', len(self.samples))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        img_path, mask_path = self.samples[idx]
        image = cv2.imread(img_path)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)

        # redimensionar
        image = cv2.resize(image, self.img_size, interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask, self.img_size, interpolation=cv2.INTER_NEAREST)

        # normalizar imagen a [-1, 1]
        image = image.astype(np.float32) / 127.5 - 1.0
        image = torch.from_numpy(image).permute(2, 0, 1)

        # máscara: long tensor
        mask = torch.from_numpy(mask.astype(np.int64))

        if self.augment:
            image, mask = self._augment(image, mask)

        return image, mask

    def _augment(self, image, mask):
        if random.random() > 0.5:
            image = torch.flip(image, dims=[2])
            mask = torch.flip(mask, dims=[1])
        if random.random() > 0.5:
            image = torch.flip(image, dims=[1])
            mask = torch.flip(mask, dims=[0])
        return image, mask


def dice_loss(pred, target, smooth=1.0):
    """Dice loss multiclase."""
    pred = torch.softmax(pred, dim=1)
    target_onehot = torch.zeros_like(pred)
    target_onehot.scatter_(1, target.unsqueeze(1), 1)
    intersection = (pred * target_onehot).sum(dim=(2, 3))
    union = pred.sum(dim=(2, 3)) + target_onehot.sum(dim=(2, 3))
    dice = (2.0 * intersection + smooth) / (union + smooth)
    return 1.0 - dice.mean()


def train_epoch(model, loader, optimizer, criterion, device):
    model.train()
    total_loss = 0
    for images, masks in loader:
        images = images.to(device)
        masks = masks.to(device)
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, masks) + dice_loss(outputs, masks)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(loader)


@torch.no_grad()
def validate(model, loader, criterion, device):
    model.eval()
    total_loss = 0
    correct = 0
    total = 0
    for images, masks in loader:
        images = images.to(device)
        masks = masks.to(device)
        outputs = model(images)
        loss = criterion(outputs, masks) + dice_loss(outputs, masks)
        total_loss += loss.item()
        pred = outputs.argmax(dim=1)
        correct += (pred == masks).sum().item()
        total += masks.numel()
    acc = correct / total
    return total_loss / len(loader), acc


def main():
    parser = argparse.ArgumentParser(description='Entrenar U-Net para planos')
    parser.add_argument('--data-dir', type=str,
                        default='data/segmentation',
                        help='Directorio raíz del dataset')
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--img-size', type=int, nargs=2, default=(512, 512))
    parser.add_argument('--resume', type=str, default=None,
                        help='Ruta a checkpoint para reanudar')
    parser.add_argument('--save-dir', type=str, default='media/models')
    args = parser.parse_args()

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    logger.info('Dispositivo: %s', device)

    data_dir = Path(args.data_dir)
    train_dir = data_dir / 'train'
    val_dir = data_dir / 'val'

    train_dataset = FloorPlanDataset(
        train_dir / 'images', train_dir / 'masks',
        img_size=tuple(args.img_size), augment=True,
    )
    val_dataset = FloorPlanDataset(
        val_dir / 'images', val_dir / 'masks',
        img_size=tuple(args.img_size), augment=False,
    )

    train_loader = DataLoader(
        train_dataset, batch_size=args.batch_size,
        shuffle=True, num_workers=2, pin_memory=True,
    )
    val_loader = DataLoader(
        val_dataset, batch_size=args.batch_size,
        shuffle=False, num_workers=2, pin_memory=True,
    )

    model = UNet(n_channels=3, n_classes=N_CLASSES).to(device)
    optimizer = optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = nn.CrossEntropyLoss()

    start_epoch = 0
    if args.resume:
        checkpoint = torch.load(args.resume, map_location=device, weights_only=True)
        model.load_state_dict(checkpoint['model_state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        start_epoch = checkpoint['epoch']
        logger.info('Reanudando desde epoch %d', start_epoch)

    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    writer = SummaryWriter(log_dir=str(save_dir / 'logs'))
    best_val_loss = float('inf')

    for epoch in range(start_epoch, args.epochs):
        train_loss = train_epoch(model, train_loader, optimizer, criterion, device)
        val_loss, val_acc = validate(model, val_loader, criterion, device)
        scheduler.step()

        writer.add_scalar('Loss/train', train_loss, epoch)
        writer.add_scalar('Loss/val', val_loss, epoch)
        writer.add_scalar('Acc/val', val_acc, epoch)

        logger.info(
            'Epoch %3d/%d  train_loss=%.4f  val_loss=%.4f  val_acc=%.3f',
            epoch + 1, args.epochs, train_loss, val_loss, val_acc,
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            checkpoint = {
                'epoch': epoch + 1,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'val_loss': val_loss,
                'val_acc': val_acc,
            }
            path = save_dir / 'unet_segmentation.pt'
            torch.save(checkpoint, path)
            logger.info('Checkpoint guardado: %s', path)

    writer.close()
    logger.info('Entrenamiento completado')


if __name__ == '__main__':
    main()
