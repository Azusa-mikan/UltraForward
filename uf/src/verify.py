# Copyright 2025 TianmuTNT
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# This file is based on zzyCaptcha (https://github.com/TianmuTNT/zzyCaptcha)
# and has been adapted for use in UltraForward.
# Modifications by Azusa-Mikan, 2026.
# See THIRD_PARTY_LICENSES/LICENSE.txt in the project root directory for the full license text.

from enum import Enum
from typing import Any
from numpy.typing import NDArray
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import asyncio
from pathlib import Path
import secrets

class VerifyType(Enum):
    BLOCK = "block"
    VERIFY = "verify"
    VERIFY_ATTEMPTS = "verify_attempts"

class Visual:
    def __init__(self) -> None:
        self.width: int = 320
        self.height: int = 120
        self.channels: int = 3
        self.font_size: int = 75
        self.font_path: Path = Path(__file__).resolve().parent / "assets" / "MonaspaceNeon-WideBold.otf"
        self.scroll_speed: int = 2
        self.loop_frames: int = 30
        self.allowed_chars = "ABCEFHJKLMNPRTVXYZ"

    def _create_text_mask(self, text: str, font_size: int, offset: tuple[int, int]) -> NDArray[Any]:
        mask = np.zeros((self.height, self.width), dtype=bool)
        font = ImageFont.truetype(self.font_path, font_size)
        img = Image.new('L', (self.width, self.height), 0)
        draw = ImageDraw.Draw(img)
        draw.text(offset, text, font=font, fill=255)
        text_layer = np.array(img)
        mask[text_layer > 128] = True
        return mask

    def _generate_looping_noise(self, width: int, height: int, channels: int) -> NDArray[Any]:
        noise = np.random.choice([0, 255], size=(height, width), p=[0.5, 0.5]).astype(np.uint8)
        return np.stack([noise] * channels, axis=-1)

    def _generate_frame(self, frame_index: int, text_mask: NDArray[Any], noise_texture: NDArray[Any]) -> NDArray[Any]:
        frame = np.zeros((self.height, self.width, self.channels), dtype=np.uint8)
        noise_height = noise_texture.shape[0]
        y_coords = np.arange(self.height).reshape(-1, 1)
        x_coords = np.arange(self.width).reshape(1, -1)
        text_offset = (frame_index * self.scroll_speed)
        bg_offset = -(frame_index * self.scroll_speed)
        text_noise_y = (y_coords + text_offset) % noise_height
        bg_noise_y = (y_coords + bg_offset) % noise_height
        text_pixels = noise_texture[text_noise_y, x_coords]
        bg_pixels = noise_texture[bg_noise_y, x_coords]
        frame[text_mask] = text_pixels[text_mask]
        frame[~text_mask] = bg_pixels[~text_mask]
        return frame

    def sync_generate_captcha_gif(self) -> tuple[str, BytesIO]:
        """
        同步生成验证码 GIF 图片。

        Returns:
            
            tuple[str, BytesIO]: 包含验证码文本和包含验证码 GIF 图片的字节流。
        """
        captcha_text = ''.join(secrets.choice(list(self.allowed_chars)) for _ in range(5))
        text_mask = self._create_text_mask(captcha_text, self.font_size, (15, 22))
        noise_height = self.loop_frames * self.scroll_speed
        noise_texture = self._generate_looping_noise(self.width, noise_height, self.channels)
        frames = [Image.fromarray(self._generate_frame(i, text_mask, noise_texture)) for i in range(self.loop_frames)]
        gif_bytes = BytesIO()
        frames[0].save(gif_bytes, format='GIF', save_all=True, append_images=frames[1:], optimize=True, duration=40, loop=0)
        gif_bytes.seek(0)
        gif_bytes.name = "captcha.gif"
        return captcha_text, gif_bytes

    async def async_generate_captcha_gif(self) -> tuple[str, BytesIO]:
        """
        异步生成验证码 GIF 图片。

        Returns:
            
            tuple[str, BytesIO]: 包含验证码文本和包含验证码 GIF 图片的字节流。
        """
        return await asyncio.to_thread(self.sync_generate_captcha_gif)
