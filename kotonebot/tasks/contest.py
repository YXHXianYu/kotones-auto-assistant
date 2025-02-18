"""竞赛"""
import logging
from gettext import gettext as _

from kotonebot.backend.dispatch import SimpleDispatcher

from . import R
from .common import conf
from .actions.scenes import at_home, goto_home
from .actions.loading import wait_loading_end
from kotonebot import device, image, ocr, color, action, task, user, rect_expand, sleep, contains

logger = logging.getLogger(__name__)

@action('前往竞赛页面')
def goto_contest() -> bool:
    """
    前置条件：位于首页 \n
    结束状态：位于竞赛界面，且已经点击了各种奖励领取提示

    :return: 是否存在未完成的挑战
    """
    # TODO: 优化这一部分，加入区域检测，提高速度
    device.click(image.expect(R.Common.ButtonContest))
    ocr.expect_wait(contains('CONTEST'))
    btn_contest = ocr.expect_wait(contains('コンテスト'))
    has_ongoing_contest = image.find(R.Daily.TextContestLastOngoing) is not None
    device.click(btn_contest)
    if not has_ongoing_contest:
        while not image.find(R.Daily.ButtonContestRanking):
            # [screenshots/contest/acquire1.png]
            # [screenshots/contest/acquire2.png]
            device.click_center()
            sleep(1)
        # [screenshots/contest/main.png]
    else:
        image.expect_wait(R.Daily.ButtonContestChallengeStart)
    return has_ongoing_contest

@action('选择并挑战')
def pick_and_contest(has_ongoing_contest: bool = False) -> bool:
    """
    选择并挑战

    前置条件：位于竞赛界面 \n
    结束状态：位于竞赛界面

    :param has_ongoing_contest: 是否有中断未完成的挑战
    :return: 如果返回假，说明今天挑战次数已经用完了
    """
    # 判断是否有中断未完成的挑战
    # [screenshots/contest/ongoing.png]
    if not has_ongoing_contest:
        image.expect_wait(R.Daily.ButtonContestRanking)
        sleep(1) # 等待动画
        logger.info('Randomly pick a contestant and start challenge.')
        # 随机选一个对手 [screenshots/contest/main.png]
        logger.debug('Clicking on contestant.')
        contestant = image.wait_for(R.Daily.TextContestOverallStats, timeout=2)
        if contestant is None:
            logger.info('No contestant found. Today\'s challenge points used up.')
            return False
        device.click(contestant)
        # 挑战开始 [screenshots/contest/start1.png]
        logger.debug('Clicking on start button.')
        device.click(image.expect_wait(R.Daily.ButtonContestStart))
    sleep(1)
    # 进入挑战页面 [screenshots/contest/contest1.png]
    # [screenshots/contest/contest2.png]
    while not image.find(R.Daily.ButtonContestChallengeStart):
        # 记忆未编成 [screenshots/contest/no_memo.png]
        if image.find(R.Daily.TextContestNoMemory):
            logger.debug('Memory not set. Using auto-compilation.')
            user.warning('竞赛未编成', _('记忆未编成。将使用自动编成。'), once=True)
            device.click(image.expect(R.Daily.ButtonContestChallenge))
        logger.debug('Waiting for challenge start screen.')
    # 勾选跳过所有
    if image.find(R.Common.CheckboxUnchecked):
        logger.debug('Checking skip all.')
        device.click()
        sleep(0.5)
    # 点击 SKIP
    logger.debug('Clicking on SKIP.')
    device.click(image.expect(R.Daily.ButtonIconSkip, colored=True, transparent=True, threshold=0.999))
    while not image.wait_for(R.Common.ButtonNextNoIcon, timeout=2):
        device.click_center()
        logger.debug('Waiting for the result.')
    # [screenshots/contest/after_contest1.png]
    # 点击 次へ [screenshots/contest/after_contest2.png]
    logger.debug('Challenge finished. Clicking on next.')
    device.click()
    # 点击 終了 [screenshots/contest/after_contest3.png]
    logger.debug('Clicking on end.')
    device.click(image.expect_wait(R.Common.ButtonEnd))
    # 可能出现的奖励弹窗 [screenshots/contest/after_contest4.png]
    sleep(1)
    if image.find(R.Common.ButtonClose):
        logger.debug('Clicking on close.')
        device.click()
    # 等待返回竞赛界面
    wait_loading_end()
    image.expect_wait(R.Daily.ButtonContestRanking)
    logger.info('Challenge finished.')
    return True

@task('竞赛')
def contest():
    """"""
    if not conf().contest.enabled:
        logger.info('Contest is disabled.')
        return
    logger.info('Contest started.')
    if not at_home():
        goto_home()
    sleep(0.3)
    btn_contest = image.expect(R.Common.ButtonContest)
    notification_dot = rect_expand(btn_contest.rect, top=35, right=35)
    if not color.find_rgb('#ff104a', rect=notification_dot):
        logger.info('No action needed.')
        return
    has_ongoing_contest = goto_contest()
    while pick_and_contest(has_ongoing_contest):
        sleep(1.3)
        has_ongoing_contest = False
    goto_home()
    logger.info('Contest all finished.')
    

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] [%(name)s] [%(funcName)s] [%(lineno)d] %(message)s')
    logging.getLogger('kotonebot').setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)
    
    contest()