"""构建镜像时把 certifi 的公共 CA 与 certs/extra-ca/ 下的额外 CA 合并。

为什么需要:本机启用了 GitHub 加速器(Steam++ / Watt Toolkit)时,它会做 TLS 中间人,
容器默认 CA 校验必然失败。把它的根证书并进来才能连通。

注意:这等于让容器信任一个本地中间人根证书 —— 因此它是**可选的**,
extra-ca 目录为空时合并结果就等于纯 certifi,行为与默认完全一致。
"""

from __future__ import annotations

import glob
import pathlib

import certifi

parts = [pathlib.Path(certifi.where()).read_text(encoding="utf-8")]
extra = sorted(glob.glob("/opt/certs/extra-ca/*.pem"))
for path in extra:
    parts.append(pathlib.Path(path).read_text(encoding="utf-8"))

out = pathlib.Path("/opt/combined-ca.pem")
out.write_text("\n".join(parts), encoding="utf-8")
print(f"combined CA written: {out} (+{len(extra)} extra)")