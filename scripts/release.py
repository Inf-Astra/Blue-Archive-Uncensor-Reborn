"""发布阶段：回写仓库清单、打包 Release 附件、生成说明文档。"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import assets_update as AU
import common as C
import table_update as TU

COMPRESSION_METHODS = {
    "deflate": zipfile.ZIP_DEFLATED,
    "lzma": zipfile.ZIP_LZMA,
    "bzip2": zipfile.ZIP_BZIP2,
    "stored": zipfile.ZIP_STORED,
}


@dataclass
class ManifestStats:
    official_entries: int = 0
    modified_entries: int = 0
    official_path: Optional[Path] = None
    modified_path: Optional[Path] = None


@dataclass
class PackageResult:
    uncensor_zip: Optional[Path] = None
    restore_zip: Optional[Path] = None
    file_count: int = 0
    uncensor_bytes: int = 0
    restore_bytes: int = 0

    @property
    def has_package(self) -> bool:
        return self.uncensor_zip is not None


# --------------------------------------------------------------------------- #
# 清单回写
# --------------------------------------------------------------------------- #

def patch_manifests(
    cfg: C.Config,
    versions: Dict[str, str],
    assets: AU.AssetsResult,
    table: Optional[TU.TableResult],
    *,
    old_versions: Dict[str, str],
) -> ManifestStats:
    resource_version = versions["ResourceVersion"]
    table_version = versions.get("TableVersion", "")
    stats = ManifestStats()

    raw_path = cfg.downloads_dir / f"bundleDownloadInfo_{resource_version}.json"
    if not raw_path.is_file():
        raise FileNotFoundError(f"找不到已下载的官方清单: {raw_path}")

    # 1. 官方清单：原样保存（保持官方字节，便于将来直接对比）
    cfg.manifest_dir.mkdir(parents=True, exist_ok=True)
    official_bytes = raw_path.read_bytes()
    cfg.official_manifest.write_bytes(official_bytes)
    manifest = C.read_json(raw_path)
    index = C.check_manifest(manifest, source="官方清单")
    stats.official_entries = len(index)
    stats.official_path = cfg.official_manifest
    C.log(f"[清单] {cfg.official_manifest.name}: {len(index)} 个文件, {C.human_size(len(official_bytes))}")

    # 2. 修改清单：以官方清单为底，替换本次打包文件的 Crc / Size
    for item in assets.shipped:
        entry = index.get(item.name)
        if entry is None:
            C.warn(f"跳过清单回写：{item.name} 不在官方清单中")
            continue
        entry["Crc"] = item.md5
        entry["Size"] = item.size

    C.write_json(cfg.modified_manifest, manifest)
    stats.modified_entries = len(assets.shipped)
    stats.modified_path = cfg.modified_manifest
    C.log(
        f"[清单] {cfg.modified_manifest.name}: 修改 {stats.modified_entries} 个条目, "
        f"{C.human_size(cfg.modified_manifest.stat().st_size)}"
    )

    # 3. 状态文件：记录这两份清单对应的版本
    C.write_json(
        cfg.manifest_state,
        {
            "resourceVersion": resource_version,
            "tableVersion": table_version,
            "previousResourceVersion": old_versions.get("ResourceVersion", ""),
            "previousTableVersion": old_versions.get("TableVersion", ""),
            "officialEntries": stats.official_entries,
            "modifiedEntries": stats.modified_entries,
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    C.log(f"[清单] {cfg.manifest_state.name}: 标记版本 {resource_version} / {table_version}")
    return stats


# --------------------------------------------------------------------------- #
# 打包
# --------------------------------------------------------------------------- #

def _zip_tree(source: Path, target: Path, *, method: str, level: int) -> int:
    compression = COMPRESSION_METHODS[method]
    files = list(C.iter_files(source))
    if not files:
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    tmp.unlink(missing_ok=True)

    options: Dict[str, Any] = {
        "compression": compression,
        "allowZip64": True,
        "strict_timestamps": False,
    }
    if compression != zipfile.ZIP_STORED:
        options["compresslevel"] = level

    C.log(
        f"[打包] {target.name}: {len(files)} 个文件, {C.human_size(C.dir_size(source))}, "
        f"压缩方式 {method}-{level}"
    )
    with zipfile.ZipFile(tmp, "w", **options) as archive:
        for order, path in enumerate(files, start=1):
            arcname = path.relative_to(source).as_posix()
            archive.write(path, arcname)
            if path.stat().st_size > 32 * 1024 * 1024:
                C.log(f"    [{order}/{len(files)}] {arcname} ({C.human_size(path.stat().st_size)})")

    os.replace(tmp, target)
    C.log(f"[打包] 完成: {C.human_size(target.stat().st_size)}")
    return len(files)


def package(
    cfg: C.Config,
    yymmdd: str,
    *,
    method: str = "deflate",
    level: int = 9,
) -> PackageResult:
    result = PackageResult()
    out_files = list(C.iter_files(cfg.out_dir))
    if not out_files:
        C.warn("out/ 为空，没有需要发布的文件")
        return result

    if method not in COMPRESSION_METHODS:
        raise ValueError(f"不支持的压缩方式: {method}")

    C.clean_dir(cfg.dist_dir)
    result.uncensor_zip = cfg.dist_dir / f"BlueArchiveCN-Uncensor-{yymmdd}.zip"
    result.file_count = _zip_tree(cfg.out_dir, result.uncensor_zip, method=method, level=level)
    result.uncensor_bytes = result.uncensor_zip.stat().st_size

    restore_files = list(C.iter_files(cfg.restore_dir))
    if restore_files:
        result.restore_zip = cfg.dist_dir / f"BlueArchiveCN-Restore-{yymmdd}.zip"
        _zip_tree(cfg.restore_dir, result.restore_zip, method=method, level=level)
        result.restore_bytes = result.restore_zip.stat().st_size
    else:
        C.warn("没有可用于 Restore 包的官方原版文件")

    C.log(
        f"[打包] Uncensor {C.human_size(result.uncensor_bytes)}"
        + (f", Restore {C.human_size(result.restore_bytes)}" if result.restore_zip else "")
    )
    return result


# --------------------------------------------------------------------------- #
# Release 说明
# --------------------------------------------------------------------------- #

def _bundle_table(items: Sequence[AU.ShippedBundle]) -> str:
    lines = [
        "| 文件 | 类型 | 来源 | 替换贴图 | 大小 | MD5 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        kind = "贴图补丁" if item.kind == "patched" else "exclusions"
        if item.upstream_changed:
            origin = "本次变化"
        elif item.carried:
            origin = "继承"
        elif item.kind == "exclusion":
            origin = "首次纳入"
        else:
            origin = "重新生成"
        textures = str(item.textures) if item.kind == "patched" else "-"
        lines.append(
            f"| `{item.name}` | {kind} | {origin} | {textures} | {C.human_size(item.size)} | `{item.md5}` |"
        )
    return "\n".join(lines)


def build_notes(
    *,
    versions: Dict[str, str],
    old_versions: Dict[str, str],
    assets: AU.AssetsResult,
    table: Optional[TU.TableResult],
    manifests: ManifestStats,
    package: PackageResult,
    yymmdd: str,
) -> str:
    patched = [item for item in assets.shipped if item.kind == "patched"]
    excluded = [item for item in assets.shipped if item.kind == "exclusion"]

    parts: List[str] = []

    parts.append("## AssetBundles 变化速览")
    parts.append("")
    parts.append(
        f"- 上游差异：新增 {len(assets.official_added)} · CRC 变化 {len(assets.official_changed)} · "
        f"删除 {len(assets.official_removed)}"
    )
    parts.append(
        f"- 打包：{len(assets.shipped)} 个（贴图补丁 {len(patched)} · exclusions {len(excluded)}），"
        f"解压后 {C.human_size(assets.total_size)}"
    )
    parts.append("")

    if patched:
        parts.append(f"<details><summary>贴图补丁明细（{len(patched)} 个）</summary>")
        parts.append("")
        parts.append(_bundle_table(patched))
        parts.append("")
        parts.append("</details>")
        parts.append("")

    if excluded:
        parts.append(f"<details><summary>exclusions 明细（{len(excluded)} 个）</summary>")
        parts.append("")
        parts.append(_bundle_table(excluded))
        parts.append("")
        parts.append("</details>")
        parts.append("")

    warnings: List[str] = []

    if assets.exclusion_upstream_changed:
        warnings.append("### exclusions 上游资源有变化")
        warnings.append("")
        warnings.append("| bundle | 旧 MD5 | 新 MD5 |")
        warnings.append("| --- | --- | --- |")
        for item in assets.shipped:
            if item.kind == "exclusion" and item.upstream_changed:
                old_crc = item.upstream_crc_old or "（新增文件）"
                warnings.append(f"| `{item.name}` | `{old_crc}` | `{item.official_crc}` |")
        warnings.append("")
        warnings.append(
            "> 这些 bundle 仍按 `assets/exclusions/` 中的本地文件打包，"
            "但上游内容已经变化，可能需要手动重新修改后再提交，否则补丁可能不完全。"
        )
        warnings.append("")

    if assets.missing_exclusions:
        warnings.append("### exclusions 在新官方清单中不存在")
        warnings.append("")
        warnings.append("> 上游可能改名或删除了这些文件，本次没有上传；请确认后更新 `assets/exclusions/`。")
        warnings.append("")
        for name in assets.missing_exclusions:
            warnings.append(f"- `{name}`")
        warnings.append("")

    if assets.unused_replacement_sets:
        warnings.append("### 贴图目录找不到对应 bundle")
        warnings.append("")
        warnings.append(
            "> 这些 `assets/replacement/` 目录在当前官方清单里匹配不到任何 bundle"
            "（上游可能改了资源名），对应的贴图**没有**被打进补丁包。需要更新目录名。"
        )
        warnings.append("")
        for name in assets.unused_replacement_sets:
            warnings.append(f"- `{name}`")
        warnings.append("")

    if assets.unmodified_exclusions:
        warnings.append("<details><summary>exclusions 与官方一致（可能还没改）</summary>")
        warnings.append("")
        warnings.append(
            f"> 共 {len(assets.unmodified_exclusions)} 个 exclusion 文件与官方 bundle 完全相同，"
            "说明它们还没被修改过（或只是占位）。如果本应修改，请检查后再提交。"
        )
        warnings.append("")
        for name in assets.unmodified_exclusions[:50]:
            warnings.append(f"- `{name}`")
        if len(assets.unmodified_exclusions) > 50:
            warnings.append(f"- ……其余 {len(assets.unmodified_exclusions) - 50} 个省略")
        warnings.append("")
        warnings.append("</details>")
        warnings.append("")

    if assets.unpatchable_carried:
        warnings.append("### 上一版补丁无法继续生成")
        warnings.append("")
        warnings.append(
            "> 这些文件在上一版修改清单里，但本次找不到对应的 `assets/replacement/` 贴图目录，"
            "将不会包含在本包与新的 Modified 清单中。"
        )
        warnings.append("")
        for name in assets.unpatchable_carried:
            warnings.append(f"- `{name}`")
        warnings.append("")

    if assets.dropped:
        warnings.append("<details><summary>上一版修改清单中已消失的文件</summary>")
        warnings.append("")
        warnings.append(
            "> 官方新清单中已不存在这些文件（上游改名或删除），本次不再提供。"
        )
        warnings.append("")
        for name in assets.dropped[:50]:
            warnings.append(f"- `{name}`")
        if len(assets.dropped) > 50:
            warnings.append(f"- ……其余 {len(assets.dropped) - 50} 个省略")
        warnings.append("")
        warnings.append("</details>")
        warnings.append("")

    if assets.repatch_changed or assets.exclusion_updated:
        warnings.append("<details><summary>本地补丁内容有变化</summary>")
        warnings.append("")
        warnings.append(
            "> 上游文件没有变化，但重新生成的补丁与上一版不同：通常是 `assets/replacement/` "
            "里的贴图更新了（exclusions 则是本地 bundle 被手动替换）。"
        )
        warnings.append("")
        for name in assets.repatch_changed:
            warnings.append(f"- 贴图补丁 `{name}`")
        for name in assets.exclusion_updated:
            warnings.append(f"- exclusions `{name}`")
        warnings.append("")
        warnings.append("</details>")
        warnings.append("")

    if assets.not_patchable:
        warnings.append("<details><summary>有差异但无需打包的 bundle</summary>")
        warnings.append("")
        warnings.append(f"> 共 {len(assets.not_patchable)} 个候选 bundle 中没有可替换贴图，按规则不打包。")
        warnings.append("")
        for name in assets.not_patchable[:50]:
            warnings.append(f"- `{name}`")
        if len(assets.not_patchable) > 50:
            warnings.append(f"- ……其余 {len(assets.not_patchable) - 50} 个省略")
        warnings.append("")
        warnings.append("</details>")
        warnings.append("")

    if warnings:
        parts.append("## ⚠️ 需要手动关注")
        parts.append("")
        parts.extend(warnings)

    parts.append("## 安装说明")
    parts.append("")
    parts.append(
        f"打开反和谐包 `BlueArchiveCN-Uncensor-{yymmdd}.zip`，内有 `AssetBundles`、`TableBundles` 两个目录。\n"
        f"将两个目录都解压到 `/storage/emulated/0/Android/data/com.RoamingStar.BlueArchive[.bilibili]/files/`，**并覆盖同名文件**。\n"
        f"如果覆盖文件后无法进入游戏，您可以使用 `BlueArchiveCN-Restore-{yymmdd}.zip`，覆盖后尝试只替换 `AssetBundles`。"
    )
    parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def write_notes(cfg: C.Config, notes: str) -> Path:
    path = cfg.dist_dir / "release-notes.md"
    cfg.dist_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(notes, encoding="utf-8")
    C.log(f"[说明] 已写入 {path}")
    return path
