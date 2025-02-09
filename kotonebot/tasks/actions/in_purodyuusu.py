import time
import random
import logging
import unicodedata
from typing import Literal
from typing_extensions import deprecated

import cv2

from .. import R
from . import loading
from .scenes import at_home
from .common import acquisitions
from ..common import conf
from kotonebot.backend.dispatch import DispatcherContext
from kotonebot.backend.util import AdaptiveWait, UnrecoverableError, crop, cropped
from kotonebot import ocr, device, contains, image, regex, action, debug, config, sleep
from .non_lesson_actions import (
    enter_allowance, allowance_available, study_available, enter_study,
    is_rest_available, rest
)

logger = logging.getLogger(__name__)

ActionType = None | Literal['lesson', 'rest']
@deprecated('OCR 方法效果不佳')
def enter_recommended_action_ocr(final_week: bool = False) -> ActionType:
    """
    在行动选择页面，执行推荐行动

    :param final_week: 是否是考试前复习周
    :return: 是否成功执行推荐行动
    """
    # 获取课程
    logger.debug("Waiting for recommended lesson...")
    with cropped(device, y1=0.00, y2=0.30):
        ret = ocr.wait_for(regex('ボーカル|ダンス|ビジュアル|休|体力'))
    logger.debug("ocr.wait_for: %s", ret)
    if ret is None:
        return None
    if not final_week:
        if "ボーカル" in ret.text:
            lesson_text = "Vo"
        elif "ダンス" in ret.text:
            lesson_text = "Da"
        elif "ビジュアル" in ret.text:
            lesson_text = "Vi"
        elif "休" in ret.text or "体力" in ret.text:
            rest()
            return 'rest'
        else:
            return None
        logger.info("Rec. lesson: %s", lesson_text)
        # 点击课程
        logger.debug("Try clicking lesson...")
        lesson_ret = ocr.expect(contains(lesson_text))
        device.double_click(lesson_ret.rect)
        return 'lesson'
    else:
        if "ボーカル" in ret.text:
            template = R.InPurodyuusu.ButtonFinalPracticeVocal
        elif "ダンス" in ret.text:
            template = R.InPurodyuusu.ButtonFinalPracticeDance
        elif "ビジュアル" in ret.text:
            template = R.InPurodyuusu.ButtonFinalPracticeVisual
        else:
            return None
        logger.debug("Try clicking lesson...")
        device.double_click(image.expect_wait(template))
        return 'lesson'

@action('执行推荐行动')
def handle_recommended_action(final_week: bool = False) -> ActionType:
    """
    在行动选择页面，执行推荐行动

    前置条件：位于行动选择页面\n
    结束状态：
        * `lesson`：练习场景，以及中间可能出现的加载、支援卡奖励、交流等
        * `rest`：休息动画。

    :param final_week: 是否是考试前复习周
    :return: 是否成功执行推荐行动
    """
    # 获取课程
    logger.debug("Getting recommended lesson...")
    with cropped(device, y1=0.00, y2=0.30):
        result = image.find_multi([
            R.InPurodyuusu.TextSenseiTipDance,
            R.InPurodyuusu.TextSenseiTipVocal,
            R.InPurodyuusu.TextSenseiTipVisual,
            R.InPurodyuusu.TextSenseiTipRest,
        ])
    logger.debug("image.find_multi: %s", result)
    if result is None:
        logger.debug("No recommended lesson found")
        return None
    if not final_week:
        if result.index == 0:
            lesson_text = contains("Da")
        elif result.index == 1:
            lesson_text = regex("Vo|V0")
        elif result.index == 2:
            lesson_text = contains("Vi")
        elif result.index == 3:
            rest()
            return 'rest'
        else:
            return None
        logger.info("Rec. lesson: %s", lesson_text)
        # 点击课程
        logger.debug("Try clicking lesson...")
        lesson_ret = ocr.expect(lesson_text)
        device.double_click(lesson_ret.rect)
        return 'lesson'
    else:
        if result.index == 0:
            template = R.InPurodyuusu.ButtonFinalPracticeDance
        elif result.index == 1:
            template = R.InPurodyuusu.ButtonFinalPracticeVocal
        elif result.index == 2:
            template = R.InPurodyuusu.ButtonFinalPracticeVisual
        else:
            return None
        logger.debug("Try clicking lesson...")
        device.double_click(image.expect_wait(template))
        return 'lesson'

def before_start_action():
    """检测支援卡剧情、领取资源等"""
    raise NotImplementedError()

@action('打出推荐卡')
# TODO: 这里面的结果也加入 debug 显示
def click_recommended_card(timeout: float = 7, card_count: int = 3) -> int:
    """点击推荐卡片
    
    :param timeout: 超时时间(秒)
    :param card_count: 卡片数量(2-4)
    :return: 执行结果。-1=失败，0~3=卡片位置，10=跳过此回合。
    """
    import cv2
    import numpy as np
    from cv2.typing import MatLike

    # 定义检测参数
    TARGET_ASPECT_RATIO_RANGE = (0.73, 0.80)
    TARGET_COLOR = (240, 240, 240)
    YELLOW_LOWER = np.array([20, 100, 100])
    YELLOW_UPPER = np.array([30, 255, 255])
    GLOW_EXTENSION = 10  # 向外扩展的像素数
    GLOW_THRESHOLD = 1200  # 荧光值阈值

    # 固定的卡片坐标 (for 720x1280)
    CARD_POSITIONS_1 = [
        # 格式：(x, y, w, h, return_value)
        (264, 883, 192, 252, 0)
    ]
    CARD_POSITIONS_2 = [
        (156, 883, 192, 252, 1),
        (372, 883, 192, 252, 2),
        # delta_x = 216, delta_x-width = 24
    ]
    CARD_POSITIONS_3 = [
        (47, 883, 192, 252, 0),  # 左卡片 (x, y, w, h)
        (264, 883, 192, 252, 1),  # 中卡片
        (481, 883, 192, 252, 2)   # 右卡片
        # delta_x = 217, delta_x-width = 25
    ]
    CARD_POSITIONS_4 = [
        (17, 883, 192, 252, 0),
        (182, 883, 192, 252, 1),
        (346, 883, 192, 252, 2),
        (511, 883, 192, 252, 3),
        # delta_x = 165, delta_x-width = -27
    ]
    SKIP_POSITION = (621, 739, 85, 85, 10)

    @deprecated('此方法待改进')
    def calc_pos(card_count: int):
        # 根据卡片数量计算实际位置
        CARD_PAD = 25
        CARD_SCREEN_PAD = 17
        card_positions = []
        
        # 计算卡片位置
        if card_count == 1:
            card_positions = [CARD_POSITIONS_3[1]]  # 只使用中间位置
        else:
            # 计算原始卡片间距
            card_spacing = CARD_POSITIONS_3[1][0] - CARD_POSITIONS_3[0][0]
            card_width = CARD_POSITIONS_3[0][2]
            
            # 计算屏幕可用宽度
            screen_width = 720
            available_width = screen_width - (CARD_SCREEN_PAD * 2)
            
            # 计算使用原始间距时的总宽度
            original_total_width = (card_count - 1) * card_spacing + card_width
            
            # 判断是否需要重叠布局
            if original_total_width > available_width:
                spacing = (available_width - card_width * card_count - CARD_SCREEN_PAD * 2) // (card_count)
                start_x = CARD_SCREEN_PAD
            else:
                spacing = card_spacing
                start_x = (screen_width - original_total_width) // 2
            
            # 生成所有卡片位置
            x = start_x
            for i in range(card_count):
                y = CARD_POSITIONS_3[0][1]
                w = CARD_POSITIONS_3[0][2]
                h = CARD_POSITIONS_3[0][3]
                card_positions.append((round(x), round(y), round(w), round(h)))
                x += spacing + card_width
        return card_positions

    def calc_pos2(card_count: int):
        if card_count == 1:
            return CARD_POSITIONS_1
        elif card_count == 2:
            return CARD_POSITIONS_2
        elif card_count == 3:
            return CARD_POSITIONS_3
        elif card_count == 4:
            return CARD_POSITIONS_4
        else:
            raise ValueError(f"Unsupported card count: {card_count}")

    if card_count == 4:
        # 随机选择一张卡片点击
        # TODO: 支持对四张卡片进行检测
        logger.warning("4 cards detected, detecting glowing card in 4 cards is not supported yet.")
        logger.info("Click random card")
        card_index = random.randint(0, 3)
        device.click(CARD_POSITIONS_4[card_index][:4])
        sleep(1)
        device.click(CARD_POSITIONS_4[card_index][:4])
        return card_index

    start_time = time.time()
    while time.time() - start_time < timeout:
        img = device.screenshot()

        # 检测卡片
        card_glows = []
        for x, y, w, h, return_value in calc_pos2(card_count) + [SKIP_POSITION]:
            # 获取扩展后的卡片区域坐标
            outer_x = max(0, x - GLOW_EXTENSION)
            outer_y = max(0, y - GLOW_EXTENSION)
            outer_w = w + (GLOW_EXTENSION * 2)
            outer_h = h + (GLOW_EXTENSION * 2)
            
            # 获取内外两个区域
            outer_region = img[outer_y:y+h+GLOW_EXTENSION, outer_x:x+w+GLOW_EXTENSION]
            inner_region = img[y:y+h, x:x+w]
            
            # 创建掩码
            outer_hsv = cv2.cvtColor(outer_region, cv2.COLOR_BGR2HSV)
            inner_hsv = cv2.cvtColor(inner_region, cv2.COLOR_BGR2HSV)
            
            # 计算外部区域的黄色部分
            outer_mask = cv2.inRange(outer_hsv, YELLOW_LOWER, YELLOW_UPPER)
            inner_mask = cv2.inRange(inner_hsv, YELLOW_LOWER, YELLOW_UPPER)
            
            # 创建环形区域的掩码（仅计算扩展区域的荧光值）
            ring_mask = outer_mask.copy()
            ring_mask[GLOW_EXTENSION:GLOW_EXTENSION+h, GLOW_EXTENSION:GLOW_EXTENSION+w] = 0
            
            # 计算环形区域的荧光值
            glow_value = cv2.countNonZero(ring_mask)
            
            card_glows.append((x, y, w, h, glow_value, return_value))

        # 找到荧光值最高的卡片
        if not card_glows:
            logger.debug("No glowing card found, retrying...")
            continue
        else:
            max_glow_card = max(card_glows, key=lambda x: x[4])
            x, y, w, h, glow_value, return_value = max_glow_card
            if glow_value < GLOW_THRESHOLD:
                logger.debug("Glow value is too low, retrying...")
                continue
            
            # 点击卡片中心
            logger.debug(f"Click glowing card at: ({x + w//2}, {y + h//2})")
            device.click(x + w//2, y + h//2)
            sleep(random.uniform(0.5, 1.5))
            device.click(x + w//2, y + h//2)
            # 体力溢出提示框
            # 跳过回合提示框 [screenshots/produce/in_produce/skip_turn_popup.png]
            while image.wait_for(R.Common.ButtonIconCheckMark, timeout=1):
                logger.info("Confirmation dialog detected")
                device.click()
            if return_value == 10:
                logger.info("No enough AP. Skip this turn")
            elif return_value == -1:
                logger.warning("No glowing card found")
            else:
                logger.info("Recommended card is Card %d", return_value + 1)
            return return_value
    return -1


@action('获取当前卡片数量')
def skill_card_count():
    """获取当前持有的技能卡数量"""
    device.click(0, 0)
    sleep(0.5)
    img = device.screenshot()
    img = crop(img, y1=0.83, y2=0.90)
    count = image.raw().count(img, R.InPurodyuusu.A, threshold=0.85)
    count += image.raw().count(img, R.InPurodyuusu.M, threshold=0.85)
    logger.info("Current skill card count: %d", count)
    return count

@action('获取剩余回合数和积分')
def remaing_turns_and_points():
    """获取剩余回合数和积分"""
    ret = ocr.ocr()
    logger.debug("ocr.ocr: %s", ret)
    def index_of(text: str) -> int:
        for i, item in enumerate(ret):
            # ＣＬＥＡＲまで -> CLEARまで
            if text == unicodedata.normalize('NFKC', item.text):
                return i
        return -1
    turns_tip_index = index_of("残りターン数")
    points_tip_index = index_of("CLEARまで")
    turns_rect = ret[turns_tip_index].rect
    # 向下扩展100像素
    turns_rect_extended = (
        turns_rect[0],  # x
        turns_rect[1],  # y 
        turns_rect[2],  # width
        turns_rect[3] + 100  # height + 100
    )
    
    # 裁剪并再次识别
    turns_img = device.screenshot()[
        turns_rect_extended[1]:turns_rect_extended[1]+turns_rect_extended[3],
        turns_rect_extended[0]:turns_rect_extended[0]+turns_rect_extended[2]
    ]
    turns_ocr = ocr.raw().ocr(turns_img)
    logger.debug("turns_ocr: %s", turns_ocr)


@action('等待进入行动场景')
def until_action_scene():
    """等待进入行动场景"""
    # 检测是否到行动页面
    while not image.wait_for_any([
        R.InPurodyuusu.TextPDiary, # 普通周
        R.InPurodyuusu.ButtonFinalPracticeDance # 离考试剩余一周
    ], timeout=1):
        logger.info("Action scene not detected. Retry...")
        acquisitions()
        sleep(1)
    else:
        logger.info("Now at action scene.")
        return 

@action('等待进入练习场景')
def until_practice_scene():
    """等待进入练习场景"""
    while image.wait_for(R.InPurodyuusu.TextClearUntil, timeout=1) is None:
        acquisitions()
        sleep(1)

@action('等待进入考试场景')
def until_exam_scene():
    """等待进入考试场景"""
    while ocr.find(regex("合格条件|三位以上")) is None:
        acquisitions()
        sleep(1)

@action('执行练习')
def practice():
    """执行练习"""
    logger.info("Practice started")
    # 循环打出推荐卡
    while True:
        with device.pinned():
            count = skill_card_count()
            if count == 0:
                logger.info("No skill card found. Wait and retry...")
                if not image.find_multi([
                    R.InPurodyuusu.TextPerfectUntil,
                    R.InPurodyuusu.TextClearUntil
                ]):
                    logger.info("PERFECTまで/CLEARまで not found. Practice finished.")
                    break
                sleep(3)
                continue
        if click_recommended_card(card_count=count) == -1:
            logger.info("Click recommended card failed. Retry...")
            continue
        logger.info("Wait for next turn...")
        sleep(9)
    # 跳过动画
    logger.info("Recommend card not found. Practice finished.")
    ocr.expect_wait(contains("上昇"))
    logger.info("Click to finish 上昇 ")
    device.click_center()

@action('执行考试')
def exam():
    """执行考试"""
    logger.info("Exam started")
    # 循环打出推荐卡
    while True:
        count = skill_card_count()
        if count == 0:
            logger.info("No skill card found. Wait and retry...")
            if not image.wait_for(R.InPurodyuusu.TextButtonExamSkipTurn, timeout=20):
                logger.info("Exam skip turn button not found. Exam finished.")
                break
            sleep(3)
            continue
        if click_recommended_card(card_count=count) == -1:
            logger.info("Click recommended card failed. Retry...")
            continue
        logger.info("Wait for next turn...")
        sleep(9)
    
    # 点击“次へ”
    device.click(image.expect_wait(R.Common.ButtonNext))
    while ocr.wait_for(contains("メモリー"), timeout=7):
        device.click_center()

@action('考试结束流程')
def produce_end():
    """执行考试结束流程"""
    bottom = (int(device.screen_size[0] / 2), int(device.screen_size[1] * 0.9))
    # 1. 考试结束交流 [screenshots/produce/in_produce/final_exam_end_commu.png]
    # 2. 然后是，考试结束对话 [screenshots\produce_end\step2.jpg]
    # 3. MV
    # 4. 培育结束交流
    # 上面这些全部一直点就可以


    # 等待选择封面画面 [screenshots/produce_end/select_cover.jpg]
    # 次へ
    logger.info("Waiting for select cover screen...")
    wait = AdaptiveWait(timeout=60 * 5, max_interval=20)
    while not image.find(R.InPurodyuusu.ButtonNextNoIcon):
        wait()
        device.click(0, 0)
    # 选择封面
    logger.info("Use default cover.")
    sleep(3)
    logger.debug("Click next")
    device.click(image.expect_wait(R.InPurodyuusu.ButtonNextNoIcon))
    sleep(1)
    # 确认对话框 [screenshots/produce_end/select_cover_confirm.jpg]
    # 決定
    logger.debug("Click Confirm")
    device.click(image.expect_wait(R.Common.ButtonConfirm, threshold=0.8))
    sleep(1)
    # 上传图片，等待“生成”按钮
    # 注意网络可能会很慢，可能出现上传失败对话框
    logger.info("Waiting for cover uploading...")
    retry_count = 0
    MAX_RETRY_COUNT = 5
    while True:
        img = device.screenshot()
        # 处理上传失败
        if image.raw().find(img, R.InPurodyuusu.ButtonRetry):
            logger.info("Upload failed. Retry...")
            retry_count += 1
            if retry_count >= MAX_RETRY_COUNT:
                logger.info("Upload failed. Max retry count reached.")
                logger.info("Cancel upload.")
                device.click(image.expect_wait(R.InPurodyuusu.ButtonCancel))
                sleep(2)
                continue
            device.click()
        # 记忆封面保存失败提示
        elif image.raw().find(img, R.Common.ButtonClose):
            logger.info("Memory cover save failed. Click to close.")
            device.click()
        elif gen_btn := ocr.raw().find(img, contains("生成")):
            logger.info("Generate memory cover completed.")
            device.click(gen_btn)
            break
        else:
            device.click_center()
        sleep(2)
    # 后续动画
    logger.info("Waiting for memory generation animation completed...")
    while not image.find(R.InPurodyuusu.ButtonNextNoIcon):
        device.click_center()
        sleep(1)
    
    # 结算完毕
    logger.info("Finalize")
    # [screenshots/produce_end/end_next_1.jpg]
    logger.debug("Click next 1")
    device.click(image.expect_wait(R.InPurodyuusu.ButtonNextNoIcon))
    sleep(1.3)
    # [screenshots/produce_end/end_next_2.png]
    logger.debug("Click next 2")
    device.click(image.expect_wait(R.InPurodyuusu.ButtonNextNoIcon))
    sleep(1.3)
    # [screenshots/produce_end/end_next_3.png]
    logger.debug("Click next 3")
    device.click(image.expect_wait(R.InPurodyuusu.ButtonNextNoIcon))
    sleep(1.3)
    # [screenshots/produce_end/end_complete.png]
    logger.debug("Click complete")
    device.click(image.expect_wait(R.InPurodyuusu.ButtonComplete))
    sleep(1.3)
    # 点击结束后可能还会弹出来：
    # 活动进度、关注提示
    # [screenshots/produce_end/end_activity.png]
    # [screenshots/produce_end/end_activity1.png]
    # [screenshots/produce_end/end_follow.png]
    while not at_home():
        if image.find(R.Common.ButtonClose):
            logger.info("Activity award claim dialog found. Click to close.")
            device.click()
        elif image.find(R.Common.ButtonNextNoIcon):
            logger.debug("Click next")
            device.click(image.expect_wait(R.Common.ButtonNextNoIcon))
        elif image.find(R.InPurodyuusu.ButtonCancel):
            logger.info("Follow producer dialog found. Click to close.")
            if conf().produce.follow_producer:
                logger.info("Follow producer")
                device.click(image.expect_wait(R.InPurodyuusu.ButtonFollowNoIcon))
            else:
                logger.info("Skip follow producer")
                device.click()
        else:
            device.click_center()
        sleep(1)
    logger.info("Produce completed.")

@action('执行 Regular 培育')
def hajime_regular(week: int = -1, start_from: int = 1):
    """
    「初」 Regular 模式

    :param week: 第几周，从1开始，-1表示全部
    :param start_from: 从第几周开始，从1开始。
    """
    def week_lesson():
        until_action_scene()
        executed_action = handle_recommended_action()
        logger.info("Executed recommended action: %s", executed_action)
        if executed_action == 'lesson':
            sleep(5)
            until_practice_scene()
            practice()
        elif executed_action == 'rest':
            pass
        elif executed_action is None:
            rest()
        until_action_scene()
        
    def week_non_lesson():
        """非练习周。可能可用行动包括：おでかけ、相談、活動支給、授業"""
        until_action_scene()
        if handle_recommended_action() == 'rest':
            logger.info("Recommended action is rest.")
        elif allowance_available():
            enter_allowance()
        elif study_available():
            enter_study()
        elif is_rest_available():
            rest()
        else:
            raise ValueError("No action available.")
        until_action_scene()

    def week_normal():
        until_action_scene()
        executed_action = handle_recommended_action()
        logger.info("Executed recommended action: %s", executed_action)
        # 推荐练习
        if executed_action == 'lesson':
            until_practice_scene()
            practice()
        # 推荐休息
        elif executed_action == 'rest':
            pass
        # 没有推荐行动
        elif executed_action is None:
            if allowance_available():
                enter_allowance()
            elif study_available():
                enter_study()
            elif is_rest_available():
                rest()
            else:
                raise ValueError("No action available.")
        until_action_scene()

    def week_final_lesson():
        if handle_recommended_action(final_week=True) != 'lesson':
            raise ValueError("Failed to enter recommended action on final week.")
        sleep(5)
        until_practice_scene()
        practice()
        # until_exam_scene()
    
    def week_mid_exam():
        logger.info("Week mid exam started.")
        logger.info("Wait for exam scene...")
        until_exam_scene()
        logger.info("Exam scene detected.")
        sleep(5)
        device.click_center()
        sleep(5)
        exam()
        until_action_scene()
    
    def week_final_exam():
        logger.info("Week final exam started.")
        logger.info("Wait for exam scene...")
        until_exam_scene()
        logger.info("Exam scene detected.")
        sleep(5)
        device.click_center()
        sleep(0.5)
        loading.wait_loading_end()
        exam()
        produce_end()
    
    weeks = [
        # TODO: 似乎一部分选项是随机出现的
        week_normal, # 1: Vo.レッスン、Da.レッスン、Vi.レッスン
        week_normal, # 2: 授業
        week_normal, # 3: Vo.レッスン、Da.レッスン、Vi.レッスン、授業
        week_normal, # 4: おでかけ、相談、活動支給
        week_final_lesson, # 5: 追い込みレッスン
        week_mid_exam, # 6: 中間試験
        week_normal, # 7: おでかけ、活動支給
        week_normal, # 8: 授業、活動支給
        week_normal, # 9: Vo.レッスン、Da.レッスン、Vi.レッスン
        week_normal, # 10: Vo.レッスン、Da.レッスン、Vi.レッスン、授業
        week_normal, # 11: おでかけ、相談、活動支給
        week_final_lesson, # 12: 追い込みレッスン
        week_final_exam, # 13: 最終試験
    ]
    if week not in [6, 13] and start_from not in [6, 13]:
        until_action_scene()
    else:
        until_exam_scene()
    if week != -1:
        logger.info("Week %d started.", week)
        weeks[week - 1]()
    else:
        for i, w in enumerate(weeks[start_from-1:]):
            logger.info("Week %d started.", i + start_from)
            w()

@action('是否在考试场景')
def is_exam_scene():
    """是否在考试场景"""
    return ocr.find(contains('残りターン'), rect=R.InPurodyuusu.BoxExamTop) is not None

ProduceStage = Literal[
    'action', # 行动场景
    'practice', # 练习场景
    'exam-start', # 考试开始确认页面
    'exam-ongoing', # 考试进行中
    'exam-end', # 考试结束
    'unknown', # 未知场景
]

@action('检测当前培育场景', dispatcher=True)
def detect_regular_produce_scene(ctx: DispatcherContext) -> ProduceStage:
    """
    判断当前是培育的什么阶段，并开始 Regular 培育。

    前置条件：培育中的任意场景\n
    结束状态：游戏主页面\n
    """
    logger.info("Detecting current produce stage...")
    
    # 行动场景
    texts = ocr.ocr(rect=R.InPurodyuusu.BoxWeeksUntilExam)
    if (
        image.find_multi([
            R.InPurodyuusu.TextPDiary, # 普通周
            R.InPurodyuusu.ButtonFinalPracticeDance # 离考试剩余一周
        ]) 
        and (texts.where(contains('週')).first())
    ):
        week = texts.squash().numbers()
        if week:
            logger.info("Detection result: At action scene. Current week: %d", week[0])
            ctx.finish()
            return 'action'
        else:
            return 'unknown'
    elif is_exam_scene():
        logger.info("Detection result: At exam scene.")
        ctx.finish()
        return 'exam-ongoing'
    else:
        return 'unknown'

@action('开始 Regular 培育')
def hajime_regular_from_stage(stage: ProduceStage):
    """
    开始 Regular 培育。
    """
    if stage == 'action':
        texts = ocr.ocr(rect=R.InPurodyuusu.BoxWeeksUntilExam)
        # 提取周数
        remaining_week = texts.squash().numbers()
        if not remaining_week:
            raise UnrecoverableError("Failed to detect week.")
        # 判断阶段
        if texts.where(contains('中間')):
            week = 6 - remaining_week[0]
            hajime_regular(start_from=week)
        elif texts.where(contains('最終')):
            week = 13 - remaining_week[0]
            hajime_regular(start_from=week)
        else:
            raise UnrecoverableError("Failed to detect produce stage.")
    elif stage == 'exam-ongoing':
        # TODO: 应该直接调用 week_final_exam 而不是再写一次
        logger.info("Exam ongoing. Start exam.")
        exam()
        produce_end()
    else:
        raise UnrecoverableError(f'Cannot resume produce REGULAR from stage "{stage}".')

@action('继续 Regular 培育')
def resume_regular_produce():
    """
    继续 Regular 培育。
    """
    hajime_regular_from_stage(detect_regular_produce_scene())

if __name__ == '__main__':
    from logging import getLogger

    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s')
    getLogger('kotonebot').setLevel(logging.DEBUG)
    getLogger(__name__).setLevel(logging.DEBUG)

    stage = (detect_regular_produce_scene())
    hajime_regular_from_stage(stage)

    # click_recommended_card(card_count=skill_card_count())
    # exam()

    # hajime_regular(start_from=7)

    # import cv2
    # while True:
    #     img = device.screenshot()
    #     cv2.imshow('123', img)
    #     cv2.waitKey(1)
