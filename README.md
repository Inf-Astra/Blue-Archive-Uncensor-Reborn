# BlueArchive-CN-Uncensor

基于 GitHub Action 的《蔚蓝档案》简中服资源自动化修改项目。

## 一、修改内容
**AssetBundles:**

即后缀 .bundle 的各类资源。

- 部分角色立绘（包含 NPC 角色）
- 部分 UI 贴图（MomoTalk 等 ImageFont）
- 部分 UI Prefabs （如角色简介隐藏的信息栏目、部分按钮位置等）

**TableBundles:**

本项目以一个手动修改过的旧 ExcelDB 为基础，对新的 ExcelDB.db 进行 SQL UPDATE 来实现文本的自动修改。

- 各类剧情、对话文本（位于 `ScenarioScriptDBSchema` 和`CharacterDialogDBSchema`）
- 各类 UI 文本（桃信 -> MomoTalk, 等级 -> Lv. 等 UI 文本，位于 `LocalizeDBSchema` 和 `LocalizeEtcSchema`）


## 二、本地运行
本项目同样兼容本地运行:
```
git clone https://github.com/InfiniteAstra/Blue-Archive-Uncensor-Reborn.git
```
```
python -m pip install -r requirements.txt

# 仅获取当前资源版本，不进行资源拉取和修改
python scripts/get_version.py --check

# 完整运行（产物在 work/、out/、dist/，会改写 current.txt 与 manifest/）
python scripts/update_all.py

# 跳过修改 TableBundles
python scripts/update_all.py --skip-table

# 用指定的旧清单模拟一次版本变化（调试用）
python scripts/update_all.py --force --skip-table \
    --baseline-manifest work/old_official.json \
    --manifest-dir work/test/manifest --out-dir work/test/out \
    --dist-dir work/test/dist --work-dir work/test/work \
    --current work/test/current.txt --date 261015
```

也可单独使用两个工具脚本：

```
# 手动修改某个 bundle 的贴图（按目录名自动匹配 assets/replacement/<前缀>）
python scripts/replace_texture.py --bundle some.bundle --replacement assets/replacement \
    --output out/AssetBundles/some.bundle

# 批量处理一个目录
python scripts/replace_texture.py --bundle-dir work/downloads/bundles \
    --replacement assets/replacement --output-dir out/AssetBundles

# 手动修改 ExcelDB
python scripts/update_exceldb.py --old ExcelDB_old.db --new ExcelDB_new.db --out ExcelDB_patched.db
```

## 三、替换方法
> [!TIP]
> 本仓库的 Release 仅适用于 Android 平台。不同平台的游戏资源不尽相同，建议谨慎在其它平台使用。
> 
> 在替换资源前，请先确保您可以正常读写`/storage/emulated/0/Android/data/`。
> 如果无法读写，建议使用 ADB 或无线调试（Android 11+）授予文件管理器权限。

* 定位到`/storage/emulated/0/Android/data/com.RoamingStar.BlueArchive[.bilibili]/files`。正常情况下，这里应当存在 AssetBundles 和 TableBundles 等目录。如果是空白的，说明您的设备未能正常读写`/storage/emulated/0/Android/data/`。
* 打开从 Release 下载的 .zip 文件，将其中的 AssetBundles 和 TableBundles 目录解压到`files`目录中，覆盖游戏资源。
* 如果覆盖文件后无法进入游戏，您可以尝试只替换 `AssetBundles`，或者覆盖 Release 中的恢复包。

## 四、使用须知

> [!IMPORTANT]
> 本项目仅供学习和展示用途。
> 所有通过本项目获取的内容均应仅用于合法和正当的目的。开发者不对任何因使用本项目而引发的直接或间接损失、损害、法律责任或其他后果承担任何责任。
> 用户在使用本项目时需自行承担风险，并确保遵守所有相关法律法规。严禁将本项目用于任何未经授权或非法的活动。用户应对自身的行为负责。

## 五、版权声明
* **"Blue Archive"** is a registered trademark of **NEXON Korea Corp. & NEXON GAMES Co., Ltd.** All rights reserved.
* **“蔚蓝档案”** 是 **上海星啸网络科技有限公司** 的注册商标，版权所有。

