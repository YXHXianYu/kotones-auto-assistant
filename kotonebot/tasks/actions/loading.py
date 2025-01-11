import time
from time import sleep
from logging import getLogger

import cv2
import numpy as np

from kotonebot import image, device, debug
from kotonebot.backend.debug import result

logger = getLogger(__name__)

def loading() -> bool:
    """检测是否在场景加载页面"""
    img = device.screenshot()
    # 二值化图片
    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
    # 裁剪上面 10%
    img = img[:int(img.shape[0] * 0.1), :]
    # 判断图片中颜色数量是否 <= 2
    # https://stackoverflow.com/questions/56606294/count-number-of-unique-colours-in-image
    b,g,r = cv2.split(img)
    shiftet_im = b.astype(np.int64) + 1000 * (g.astype(np.int64) + 1) + 1000 * 1000 * (r.astype(np.int64) + 1)
    ret = len(np.unique(shiftet_im)) <= 2
    result('tasks.actions.loading', img, f'result={ret}')
    return ret

def wait_loading_start(timeout: float = 60):
    """等待加载开始"""
    start_time = time.time()
    while not loading():
        if time.time() - start_time > timeout:
            raise TimeoutError('加载超时')
        logger.debug('Not loading...')
        sleep(1)

def wait_loading_end(timeout: float = 60):
    """等待加载结束"""
    start_time = time.time()
    while loading():
        if time.time() - start_time > timeout:
            raise TimeoutError('加载超时')
        logger.debug('Loading...')
        sleep(1)

if __name__ == '__main__':
    print(loading())
    input()
