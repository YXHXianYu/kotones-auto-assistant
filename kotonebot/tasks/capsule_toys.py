"""扭蛋机，支持任意次数的任意扭蛋类型"""
import logging

from kotonebot import task, action, device, image, sleep
from kotonebot.backend.image import TemplateMatchResult
from . import R
from .common import conf
from .actions.scenes import at_home, goto_home

logger = logging.getLogger(__name__)

@action('抽某种类型的扭蛋times次')
def draw_capsule_toys(button: TemplateMatchResult, times: int):
    """
    抽某种类型的扭蛋N次

    :param button: 扭蛋按钮
    :param times: 抽取次数
    """
    
    device.click(button)
    sleep(0.5)

    device.swipe(
        R.Daily.CapsuleToys.SliderStartPoint.x,
        R.Daily.CapsuleToys.SliderStartPoint.y,
        R.Daily.CapsuleToys.SliderEndPoint.x,
        R.Daily.CapsuleToys.SliderEndPoint.y,
        duration=1.0
    )
    sleep(0.5)

    # 点击加号按钮
    add_button = image.expect_wait(R.Daily.ButtonShopCountAdd, timeout=5)
    for _ in range(times):
        device.click(add_button)
    sleep(0.5)

    # 点击确认按钮
    device.click(image.expect_wait(R.Common.ButtonConfirm, timeout=5))
    sleep(0.5)

    # 点击关闭按钮（这里同时处理了两种情况：成功，关闭提示页面；扭蛋次数不足，关闭抽扭蛋页面）
    if image.wait_for(R.Common.ButtonIconClose, timeout=5):
        device.click()
        sleep(1)

@action('获取抽扭蛋按钮')
def get_capsule_toys_draw_buttons():
    """
    在扭蛋页面中获取两个抽扭蛋按钮，并按y轴排序
    """
    buttons = image.find_all(R.Daily.ButtonShopCapsuleToysDraw)
    if len(buttons) != 2:
        logger.error('Failed to find 2 capsule toys buttons.')
        return []
    # 按y轴排序
    buttons.sort(key=lambda x: x.position[1])
    return buttons

@task('扭蛋机')
def capsule_toys():
    """
    扭蛋机，支持任意次数的任意扭蛋类型

    自动化思路：\n
    进入扭蛋机页面后，可以发现扭蛋机总共有4种类型。\n
    通过硬编码的滑动翻页，把每两种扭蛋分为同一页。
    第一页：好友扭蛋+感性扭蛋；
    第二页：逻辑扭蛋+非凡扭蛋。\n
    划到某一页之后，识别截图中所有“抽扭蛋”按钮，再按照y轴排序，即可以实现选择扭蛋类型。
    """
    #[screenshots/shop/capsule_toys_upper.png]
    #[screenshots/shop/capsule_toys_lower.png]

    if not conf().capsule_toys.enabled:
        logger.info('"Capsule Toys" is disabled.')
        return
    
    if not at_home():
        goto_home()
    
    # 进入扭蛋机页面
    logger.info('Entering Capsule Toys page')
    device.click(image.expect_wait(R.Daily.ButtonShop, timeout=5))
    device.click(image.expect_wait(R.Daily.ButtonShopCapsuleToys, timeout=5))
    sleep(1)

    # 处理好友扭蛋和感性扭蛋
    buttons = get_capsule_toys_draw_buttons();
    if len(buttons) != 2:
        return

    if conf().capsule_toys.friend_capsule_toys_count > 0:
        draw_capsule_toys(buttons[0], conf().capsule_toys.friend_capsule_toys_count)
    
    if conf().capsule_toys.sense_capsule_toys_count > 0:
        draw_capsule_toys(buttons[1], conf().capsule_toys.sense_capsule_toys_count)
    
    # 划到第二页
    device.swipe(
        R.Daily.CapsuleToys.NextPageStartPoint.x,
        R.Daily.CapsuleToys.NextPageStartPoint.y,
        R.Daily.CapsuleToys.NextPageEndPoint.x,
        R.Daily.CapsuleToys.NextPageEndPoint.y,
        duration=2.0 # 划慢点，确保精确定位
                     # FIXME: adb不支持swipe duration失效
    )
    sleep(1) # 等待滑动静止（由于swipe duration失效，所以这里需要手动等待）

    # 处理逻辑扭蛋扭蛋和非凡扭蛋
    buttons = get_capsule_toys_draw_buttons();
    if len(buttons) != 2:
        return
    
    if conf().capsule_toys.logic_capsule_toys_count > 0:
        draw_capsule_toys(buttons[0], conf().capsule_toys.logic_capsule_toys_count)
    
    if conf().capsule_toys.anomaly_capsule_toys_count > 0:
        draw_capsule_toys(buttons[1], conf().capsule_toys.anomaly_capsule_toys_count)

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s] [%(lineno)d] %(message)s')
    logger.setLevel(logging.DEBUG)
    capsule_toys()

