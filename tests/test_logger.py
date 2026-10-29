import logging

import logger


def test_adds_a_console_handler_for_local_runs():
    root = logging.getLogger()
    root.handlers.clear()

    logger.setup_logging()

    assert len(root.handlers) == 1
    assert root.level == logging.INFO


def test_keeps_lambdas_handler_without_adding_another():
    root = logging.getLogger()
    root.handlers.clear()
    lambda_handler = logging.StreamHandler()
    root.addHandler(lambda_handler)

    logger.setup_logging()

    assert root.handlers == [lambda_handler]


def test_repeated_runs_do_not_stack_handlers():
    # Lambda can run the handler many times in the same process
    root = logging.getLogger()
    root.handlers.clear()

    logger.setup_logging()
    logger.setup_logging()

    assert len(root.handlers) == 1
