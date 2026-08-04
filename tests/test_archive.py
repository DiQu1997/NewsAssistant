"""archive 阶段 —— 冷热分层、冷层回落、远端可用性判定。

rclone 的"远端"用本地目录路径（rclone 本地后端），不碰外网不碰真 Drive。
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from newsassistant.archive import _remote_ready, tier_content
from newsassistant.contentstore import ContentStore

needs_rclone = pytest.mark.skipif(
    not shutil.which("rclone"), reason="rclone not installed")


def _make_store(tmp_path: Path, remote: Path | None = None) -> ContentStore:
    return ContentStore(tmp_path / "data",
                        str(remote) if remote else "")


def test_remote_ready_guards():
    assert not _remote_ready("")                       # 未配置
    assert not _remote_ready("no-such-remote:x") or \
        shutil.which("rclone") is None                 # 未登记的远端


@needs_rclone
def test_remote_ready_local_path(tmp_path):
    assert _remote_ready(str(tmp_path))                # 本地后端：路径即远端


@needs_rclone
def test_tier_and_fallback_roundtrip(tmp_path):
    data, remote = tmp_path / "data", tmp_path / "remote"
    store = ContentStore(data, str(remote))
    sha, ref = store.put("冷层往返测试正文 " * 20)

    # 文件还热：不迁
    assert tier_content(data, str(remote), cold_days=30) == {"moved": 0}

    # 把 mtime 拨老 → 迁走，本地消失，远端结构不变
    f = data / ref
    old = time.time() - 40 * 86400
    os.utime(f, (old, old))
    st = tier_content(data, str(remote), cold_days=30)
    assert st["moved"] == 1
    assert not f.exists()
    assert (remote / ref).exists()

    # get() 冷层回落 + 回填本地；ref 对上层始终稳定
    text = store.get(ref)
    assert "冷层往返测试正文" in text
    assert f.exists()                                  # cache-on-read 已回填

    # 没配远端的 store 读丢失文件 → 原样抛 FileNotFoundError
    f.unlink()
    with pytest.raises(FileNotFoundError):
        _make_store(tmp_path).get(ref)
