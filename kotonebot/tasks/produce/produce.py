import logging
from itertools import cycle
from typing import Optional, Literal

from kotonebot.backend.context.context import wait
from kotonebot.tasks.game_ui.scrollable import Scrollable
from kotonebot.ui import user
from kotonebot.util import Countdown, Interval
from kotonebot.backend.dispatch import SimpleDispatcher

from .. import R
from ..common import conf, PIdol
from ..actions.scenes import at_home, goto_home
from ..produce.in_purodyuusu import hajime_pro, hajime_regular, resume_regular_produce
from kotonebot import device, image, ocr, task, action, sleep, contains

logger = logging.getLogger(__name__)

def format_time(seconds):
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)
    return f"{minutes}m {seconds}s"

def unify(arr: list[int]):
    # 先对数组进行排序
    arr.sort()
    result = []
    i = 0
    while i < len(arr):
        # 将当前元素加入结果
        result.append(arr[i])
        # 跳过所有与当前元素相似的元素
        j = i + 1
        while j < len(arr) and abs(arr[j] - arr[i]) <= 10:
            j += 1
        i = j
    return result

@action('选择P偶像', screenshot_mode='manual-inherit')
def select_idol(target_titles: list[str] | PIdol):
    """
    选择目标P偶像

    前置条件：培育-偶像选择页面 1.アイドル選択\n
    结束状态：培育-偶像选择页面 1.アイドル選択\n

    :param target_titles: 目标偶像的名称关键字。选择时只会选择所有关键字都出现的偶像。
    """
    # 前置条件：[res/sprites/jp/produce/produce_preparation1.png]
    # 结束状态：[res/sprites/jp/produce/produce_preparation1.png]
    
    logger.info(f"Find and select idol: {target_titles}")
    # 进入总览
    device.screenshot()
    device.click(image.expect(R.Produce.ButtonPIdolOverview))
    while not image.find(R.Common.ButtonConfirmNoIcon):
        device.screenshot()

    if isinstance(target_titles, PIdol):
        target_titles = target_titles.to_title()
    _target_titles = [contains(t, ignore_case=True) for t in target_titles]
    device.screenshot()
    # 定位滑动基准
    results = image.find_all(R.Produce.IconPIdolLevel)
    results.sort(key=lambda r: tuple(r.position))
    ys = unify([r.position[1] for r in results])

    min_y = ys[0]
    max_y = ys[1]

    found = False
    max_tries = 5
    tries = 0
    sc = Scrollable()
    # 找到目标偶像
    while not found:
        # 首先检查当前选中的是不是已经是目标
        if all(ocr.find_all(_target_titles, rect=R.Produce.KbIdolOverviewName)):
            found = True
            break
        # 如果不是，就挨个选中，判断名称
        for r in results:
            device.click(r)
            sleep(0.3)
            device.screenshot(force=True)
            if all(ocr.find_all(_target_titles, rect=R.Produce.KbIdolOverviewName)):
                found = True
                break
        if not found:
            tries += 1
            if tries > max_tries:
                break
            # 翻页
            # device.swipe(x1=100, x2=100, y1=max_y, y2=min_y)
            sc.next(page=0.8)
            sleep(0.4)
            device.screenshot()
            results = image.find_all(R.Produce.IconPIdolLevel)
            results.sort(key=lambda r: tuple(r.position))

    device.click(image.expect(R.Common.ButtonConfirmNoIcon))
    return found

@action('培育开始.编成翻页', screenshot_mode='manual-inherit')
def select_set(index: int):
    """
    选择指定编号的支援卡/回忆编成。

    前置条件：STEP 2/3 页面
    结束状态：STEP 2/3 页面

    :param index: 支援卡/回忆编成的编号，从 1 开始。
    """
    def _current():
        numbers = []
        while not numbers:
            device.screenshot()
            numbers = ocr.ocr(rect=R.Produce.BoxSetCountIndicator).squash().numbers()
            if not numbers:
                logger.warning('Failed to get current set number. Retrying...')
                sleep(0.2)
        return numbers[0]
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        current = _current()
        logger.info(f'Navigate to set #{index}. Now at set #{current}.')
        
        # 计算需要点击的次数
        click_count = abs(index - current)
        if click_count == 0:
            logger.info(f'Already at set #{current}.')
            return
        click_target = R.Produce.PointProduceNextSet if current < index else R.Produce.PointProducePrevSet
        
        # 点击
        for _ in range(click_count):
            device.click(click_target)
            sleep(0.1)
        
        # 确认
        final_current = _current()
        if final_current == index:
            logger.info(f'Arrived at set #{final_current}.')
            return
        else:
            retry_count += 1
            logger.warning(f'Failed to navigate to set #{index}. Current set is #{final_current}. Retrying... ({retry_count}/{max_retries})')
    
    logger.error(f'Failed to navigate to set #{index} after {max_retries} retries.')
    
@action('继续当前培育')
def resume_produce():
    """
    继续当前培育

    前置条件：游戏首页，且当前有进行中培育\n
    结束状态：游戏首页
    """
    # 点击 プロデュース中
    # [res/sprites/jp/daily/home_1.png]
    logger.info('Click ongoing produce button.')
    device.click(R.Produce.BoxProduceOngoing)
    # 点击 再開する
    # [res/sprites/jp/produce/produce_resume.png]
    logger.info('Click resume button.')
    device.click(image.expect_wait(R.Produce.ButtonResume))
    # 继续流程
    resume_regular_produce()

@action('执行培育', screenshot_mode='manual-inherit')
def do_produce(
    idol: PIdol,
    mode: Literal['regular', 'pro'],
    memory_set_index: Optional[int] = None
) -> bool:
    """
    进行培育流程

    前置条件：可导航至首页的任意页面\n
    结束状态：游戏首页\n
    
    :param idol: 要培育的偶像。如果为 None，则使用配置文件中的偶像。
    :param mode: 培育模式。
    :return: 是否因为 AP 不足而跳过本次培育。
    """
    if not at_home():
        goto_home()

    device.screenshot()
    # 有进行中培育的情况
    if ocr.find(contains('中'), rect=R.Produce.BoxProduceOngoing):
        logger.info('Ongoing produce found. Try to resume produce.')
        resume_produce()
        return True

    # 0. 进入培育页面
    mode_text = 'REGULAR' if mode == 'regular' else 'PRO'
    result = (SimpleDispatcher('enter_produce')
        .click(R.Produce.ButtonProduce)
        .click(contains(mode_text))
        .until(R.Produce.ButtonPIdolOverview, result=True)
        .until(R.Produce.TextAPInsufficient, result=False)
    ).run()
    if not result:
        logger.info('AP insufficient. Exiting produce.')
        device.click(image.expect_wait(R.InPurodyuusu.ButtonCancel))
        return False
    # 1. 选择 PIdol [screenshots/produce/select_p_idol.png]
    select_idol(idol.to_title())
    device.click(image.expect_wait(R.Common.ButtonNextNoIcon))
    # 2. 选择支援卡 自动编成 [screenshots/produce/select_support_card.png]
    ocr.expect_wait(contains('サポート'), rect=R.Produce.BoxStepIndicator)
    it = Interval()
    while True:
        if image.find(R.Common.ButtonNextNoIcon, colored=True):
            device.click()
            break
        elif image.find(R.Produce.ButtonAutoSet):
            device.click()
            sleep(1)
        elif image.find(R.Common.ButtonConfirm, colored=True):
            device.click()
        device.screenshot()
        it.wait()
    # 3. 选择回忆 自动编成 [screenshots/produce/select_memory.png]
    ocr.expect_wait(contains('メモリー'), rect=R.Produce.BoxStepIndicator)
    # 自动编成
    if memory_set_index is not None and not 1 <= memory_set_index <= 10:
        raise ValueError('`memory_set_index` must be in range [1, 10].')
    if memory_set_index is None:
        device.click(image.expect_wait(R.Produce.ButtonAutoSet))
        wait(0.5, before='screenshot')
        device.screenshot()
    # 指定编号
    else:
        select_set(memory_set_index)
    (SimpleDispatcher('do_produce.step_3')
        .click(R.Common.ButtonNextNoIcon)
        .click(R.Common.ButtonConfirm)
        .until(contains('開始確認'), rect=R.Produce.BoxStepIndicator)
    ).run()

    # 4. 选择道具 [screenshots/produce/select_end.png]
    # TODO: 如果道具不足，这里加入推送提醒
    if conf().produce.use_note_boost:
        if image.find(R.Produce.CheckboxIconNoteBoost):
            device.click()
            sleep(0.1)
    if conf().produce.use_pt_boost:
        if image.find(R.Produce.CheckboxIconSupportPtBoost):
            device.click()
            sleep(0.1)
    device.click(image.expect_wait(R.Produce.ButtonProduceStart))
    # 5. 相关设置弹窗 [screenshots/produce/skip_commu.png]
    cd = Countdown(5).start()
    while not cd.expired():
        device.screenshot()
        if image.find(R.Produce.RadioTextSkipCommu):
            device.click()
        if image.find(R.Common.ButtonConfirmNoIcon):
            device.click()
    if mode == 'regular':
        hajime_regular()
    else:
        hajime_pro()
    return True

@task('培育')
def produce_task(
    mode: Optional[Literal['regular', 'pro']] = None,
    count: Optional[int] = None,
    idols: Optional[list[PIdol]] = None,
    memory_sets: Optional[list[int]] = None
):
    """
    培育任务

    :param mode: 培育模式。若为 None，则从配置文件中读入。
    :param count: 培育次数。若为 None，则从配置文件中读入。
    :param idols: 要培育的偶像。若为 None，则从配置文件中读入。
    """
    if not conf().produce.enabled:
        logger.info('Produce is disabled.')
        return
    import time
    if count is None:
        count = conf().produce.produce_count
    if idols is None:
        idols = conf().produce.idols
    if memory_sets is None:
        memory_sets = conf().produce.memory_sets
    if mode is None:
        mode = conf().produce.mode
    # 数据验证
    if count < 0:
        user.warning('配置有误', '培育次数不能小于 0。将跳过本次培育。')
        return

    idol_iterator = cycle(idols)
    memory_set_iterator = cycle(memory_sets)
    for i in range(count):
        start_time = time.time()
        idol = next(idol_iterator)
        if conf().produce.auto_set_memory:
            memory_set = None
        else:
            memory_set = next(memory_set_iterator, None)
        logger.info(
            f'Produce start with: '
            f'idol: {idol.value}, mode: {mode}, memory_set: #{memory_set}'
        )
        if not do_produce(idol, mode, memory_set):
            user.info('AP 不足', f'由于 AP 不足，跳过了 {count - i} 次培育。')
            logger.info('%d produce(s) skipped because of insufficient AP.', count - i)
            break
        end_time = time.time()
        logger.info(f"Produce time used: {format_time(end_time - start_time)}")

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s] [%(lineno)d] %(message)s')
    logging.getLogger('kotonebot').setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)
    import os
    from datetime import datetime
    os.makedirs('logs', exist_ok=True)
    log_filename = datetime.now().strftime('logs/task-%y-%m-%d-%H-%M-%S.log')
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'))
    logging.getLogger().addHandler(file_handler)
    
    import time
    from kotonebot.backend.context import init_context, manual_context
    from kotonebot.tasks.common import BaseConfig
    from kotonebot.util import Profiler
    init_context(config_type=BaseConfig)
    conf().produce.enabled = True
    conf().produce.mode = 'pro'
    conf().produce.produce_count = 1
    conf().produce.idols = [PIdol.月村手毬_アイヴイ]
    conf().produce.memory_sets = [5]
    conf().produce.auto_set_memory = False
    # do_produce(PIdol.月村手毬_初声, 'pro', 5)
    produce_task()
    # a()
    # select_idol(PIdol.藤田ことね_学園生活)
    # select_set(10)
    # manual_context().begin()
    # print(ocr.ocr(rect=R.Produce.BoxSetCountIndicator).squash().numbers())