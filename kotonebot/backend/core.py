import logging
from dataclasses import dataclass
from typing import Callable, ParamSpec, TypeVar, overload

import cv2
from cv2.typing import MatLike

@dataclass
class Task:
    name: str
    description: str
    func: Callable
    priority: int
    """
    任务优先级，数字越大优先级越高。
    """

@dataclass
class Action:
    name: str
    description: str
    func: Callable
    priority: int
    """
    动作优先级，数字越大优先级越高。
    """

# TODO: 支持透明背景
class Image:
    def __init__(
        self,
        *,
        path: str | None = None,
        name: str | None = 'untitled',
        data: MatLike | None = None,
    ):
        self.path = path
        self.name = name
        self.__data = data
        self.__data_with_alpha: MatLike | None = None

    @property
    def data(self) -> MatLike:
        if self.__data is None:
            if self.path is None:
                raise ValueError('Either path or data must be provided.')
            self.__data = cv2.imread(self.path)
        return self.__data
    
    @property
    def data_with_alpha(self) -> MatLike:
        if self.__data_with_alpha is None:
            if self.path is None:
                raise ValueError('Either path or data must be provided.')
            self.__data_with_alpha = cv2.imread(self.path, cv2.IMREAD_UNCHANGED)
        return self.__data_with_alpha
    
    def __repr__(self) -> str:
        if self.path is None:
            return f'<Image: memory>'
        else:
            return f'<Image: "{self.name}" at {self.path}>'


class Ocr:
    def __init__(
        self,
        text: str | Callable[[str], bool],
        *,
        language: str = 'jp',
    ):
        self.text = text
        self.language = language


P = ParamSpec('P')
R = TypeVar('R')

logger = logging.getLogger(__name__)
task_registry: dict[str, Task] = {}
action_registry: dict[str, Action] = {}
current_callstack: list[Task|Action] = []

def _placeholder():
    raise NotImplementedError('Placeholder function')

def task(
    name: str,
    description: str|None = None,
    *,
    pass_through: bool = False,
    priority: int = 0,
):
    """
    `task` 装饰器，用于标记一个函数为任务函数。

    :param name: 任务名称
    :param description: 任务描述。如果为 None，则使用函数的 docstring 作为描述。
    :param pass_through: 
        默认情况下， @task 装饰器会包裹任务函数，跟踪其执行情况。
        如果不想跟踪，则设置此参数为 False。
    :param priority: 任务优先级，数字越大优先级越高。
    """
    def _task_decorator(func: Callable[P, R]) -> Callable[P, R]:
        nonlocal description
        description = description or func.__doc__ or ''
        task = Task(name, description, _placeholder, priority)
        task_registry[name] = task
        logger.debug(f'Task "{name}" registered.')
        if pass_through:
            return func
        else:
            def _wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                current_callstack.append(task)
                ret = func(*args, **kwargs)
                current_callstack.pop()
                return ret
            task.func = _wrapper
            return _wrapper
    return _task_decorator

@overload
def action(func: Callable[P, R]) -> Callable[P, R]: ...

@overload
def action(
    name: str,
    description: str|None = None,
    *,
    pass_through: bool = False,
    priority: int = 0,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    `action` 装饰器，用于标记一个函数为动作函数。

    :param name: 动作名称。如果为 None，则使用函数的名称作为名称。
    :param description: 动作描述。如果为 None，则使用函数的 docstring 作为描述。
    :param pass_through: 
        默认情况下， @action 装饰器会包裹动作函数，跟踪其执行情况。
        如果不想跟踪，则设置此参数为 False。
    :param priority: 动作优先级，数字越大优先级越高。
    """
    ...

def action(*args, **kwargs):
    def _register(func: Callable, name: str, description: str|None = None, priority: int = 0) -> Action:
        description = description or func.__doc__ or ''
        action = Action(name, description, func, priority)
        action_registry[name] = action
        logger.debug(f'Action "{name}" registered.')
        return action

    pass_through = kwargs.get('pass_through', True)
    priority = kwargs.get('priority', 0)
    if len(args) == 1 and isinstance(args[0], Callable):
        func = args[0]
        action = _register(_placeholder, func.__name__, func.__doc__, priority)
        if pass_through:
            return func
        else:
            def _wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                current_callstack.append(action)
                ret = func(*args, **kwargs)
                current_callstack.pop()
                return ret
            action.func = _wrapper
            return _wrapper
    else:
        name = args[0]
        description = args[1] if len(args) >= 2 else None
        def _action_decorator(func: Callable):
            nonlocal pass_through
            action = _register(_placeholder, name, description)
            pass_through = kwargs.get('pass_through', True)
            if pass_through:
                return func
            else:
                def _wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                    current_callstack.append(action)
                    ret = func(*args, **kwargs)
                    current_callstack.pop()
                    return ret
                action.func = _wrapper
                return _wrapper
        return _action_decorator

@overload
def image(data: str) -> Image:
    """从文件路径创建 Image 对象。"""
    ...
@overload
def image(data: MatLike) -> Image:
    """从 OpenCV 的 MatLike 对象创建 Image 对象。"""
    ...

def image(data: str | MatLike) -> Image:
    if isinstance(data, str):
        return Image(path=data)
    else:
        return Image(data=data)
 
def ocr(text: str | Callable[[str], bool], language: str = 'jp') -> Ocr:
    return Ocr(text, language=language)
