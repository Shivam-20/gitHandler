import json

from tools.core import get_logger


def test_get_logger_json(capsys):
    logger = get_logger('testlogger', json_out=True)
    logger.info('hello world')
    # logger writes to stderr via StreamHandler
    out = capsys.readouterr().err.strip()
    assert out
    data = json.loads(out)
    assert data['msg'] == 'hello world'
    assert data['level'] == 'INFO'
