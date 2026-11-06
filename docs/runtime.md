# 外部代码验证与 Compose 配置生成

镜像制作与运行配置是两个独立命令：`build.py` 负责构建镜像，`prepare_runtime.py` 为已有镜像生成 Compose、HOME 和账号文件。仿真和 NPU 目标均显式设置 `user: '0:0'`，以 root 运行容器。日常 Compose 命令无需逐项 export，也不需要 `.env` 或 `--env-file`。生成器不启动业务容器。

## 两步准备

在项目目录构建镜像：

```bash
python3 build.py --target simulation \
  --materials-root /data/ascend-materials
```

构建成功后，使用终端 `Report:` 输出的实际报告目录中的 `image-ref.txt` 执行下方运行配置命令。该命令在目标 Docker 服务器上执行，镜像须已存在于本地 Docker。更换代码、账号、设备或子网时只需重新生成运行配置，无需重建镜像。

| 路径 | 使用阶段与要求 |
| --- | --- |
| `build.py --materials-root` | 构建阶段，准备安装材料；默认为 `./materials` |
| `prepare_runtime.py --image-ref-file` | 运行配置阶段，指定成功构建报告中的 `image-ref.txt` |
| `prepare_runtime.py --code-dir` | 运行配置阶段，已存在且可读写的验证工作目录，可包含预构建安装包和 TTK 源码；整体挂载到 `/workspace/code` |
| `prepare_runtime.py --output-dir` | 必填，工具自动创建的运行配置目录；固定目录可保留 HOME 和缓存 |
| `home/`、`identity/` | 在运行配置目录下自动创建，无需额外指定 |
| NPU 设备和驱动路径 | 运行配置阶段检查服务器已安装资源；布局不同时通过专用参数覆盖 |

运行参数只属于 `prepare_runtime.py`，不传给 `build.py`。运行配置生成失败不改变镜像或构建报告；成功构建即发布 `image-ref.txt`。Compose 项目名按输出目录命名，同时运行多个项目时使用不同的目录名和子网。

预构建包验证的完整目录及命令示例见 [Quick Start](../README.md#quick-start)：只需交付 mock 安装包、ops_transformer 安装包和 TTK 源码，两个构建仓库的源码留在构建机器。业务包在运行容器中按各自发布说明安装，依赖声明和业务测试由对应项目维护。

## 已有镜像或在其他服务器运行

在目标 Docker 服务器上，以拥有待验证代码的普通开发用户执行。将下面路径替换为真实路径：

```bash
python3 /path/to/ascend_dev/prepare_runtime.py \
  --image-ref-file /data/build/run-001/image-ref.txt \
  --code-dir /data/operator-project \
  --output-dir /data/ascend-runtime

docker compose -f /data/ascend-runtime/compose.yaml config
docker compose -f /data/ascend-runtime/compose.yaml up -d
docker compose -f /data/ascend-runtime/compose.yaml exec ascend bash
```

镜像引用来自构建成功后生成的 `image-ref.txt`；不重新构建、不拉取镜像、不自定义 tag。准备脚本从镜像的 `dev.ascend.target` 标签识别 NPU 或仿真环境。没有该标签的兼容镜像，可用 `--target npu` 或 `--target simulation` 指定；与已有标签冲突时报错。

输出目录：

```text
ascend-runtime/
├── compose.yaml
├── home/                 # 可写 HOME、缓存，重新生成时保留
└── identity/
    ├── passwd            # 容器专用账号副本
    ├── group
    └── identity.txt      # 镜像 ID、UID/GID、用户名
```

`image`、`user`、挂载路径、NPU 设备与 `group_add` 都是已确定的具体值，不引用 `ASCEND_IMAGE`、`LOCAL_UID`、`CODE_DIR` 等终端变量。固定的容器环境变量 HOME、XDG_CACHE_HOME 仍由 YAML 设置。路径中的字面 `$` 会转义为 Compose 的 `$$`，避免意外插值。[Compose 插值规则](https://docs.docker.com/reference/compose-file/interpolation/)

## 独立生成器参数

| 参数 | 默认值或要求 |
| --- | --- |
| `--image-ref-file FILE` | 必填，构建报告中的单行镜像引用 |
| `--code-dir DIR` | 必填，已存在、可读写的外部代码目录 |
| `--output-dir DIR` | 必填，生成配置、账号文件和 HOME 的目录 |
| `--target npu\|simulation` | 默认读取镜像标签 |
| `--uid ID`、`--gid ID` | developer 账号记录的 UID/GID，默认 `os.getuid()`、`os.getgid()`，UID 必须非零；不改变容器的 root 运行身份 |
| `--user NAME` | 账号记录名称，默认 `developer`；不改变容器的 root 运行身份 |
| `--runtime-subnet CIDR` | Compose bridge 的私有 IPv4 网段，默认 `192.168.240.0/24`；两个目标均适用 |
| `--group-add GID` | 可重复，增加共享项目等所需的补充组 |
| `--device FILE` | NPU 专用，可重复；显式指定后替代默认设备清单 |
| `--driver-root DIR` | NPU 专用，默认 `/usr/local/Ascend/driver` |
| `--dcmi-dir DIR` | NPU 专用，默认 `/usr/local/dcmi` |
| `--install-info FILE` | NPU 专用，默认 `/etc/ascend_install.info` |

`build.py --output-dir` 表示构建报告根目录；`prepare_runtime.py --output-dir` 表示运行配置和 HOME 的目录。`--code-dir`、`--runtime-subnet` 及账号、设备、驱动参数仅由运行配置命令接收，原构建参数 `--runtime-dir` 已移除。

准备脚本只读取命令行和自身默认值，不继承旧的 `LOCAL_*`、`ASCEND_IMAGE`、`NPU_*_GID` 等配置变量。相对路径以调用目录为基准，生成配置使用绝对路径；可以从任意目录通过 `-f` 使用。

## 网络配置

仿真和 NPU 均使用项目独立的 bridge 网络，显式配置 IPAM 子网，默认不再由 Docker 自动选择地址池：

```yaml
networks:
  default:
    driver: bridge
    ipam:
      config:
        - subnet: '192.168.240.0/24'
```

`prepare_runtime.py` 支持 `--runtime-subnet CIDR`。该参数只控制运行网络，不影响镜像或构建参数 `--network`；网关和容器 IP 仍由 Docker 分配。输入必须是无主机位的私有 IPv4 网络地址，例如 `192.168.241.0/24`，需要至少能容纳网关和容器（前缀不大于 `/30`）。

工具校验 CIDR 格式，不自动修改宿主机路由或探测目标服务器的网络冲突。生成前核对目标服务器的路由、VPN 和已有 Docker 子网；默认范围有重叠时指定其他空闲网段。多个 Compose 项目不能共用这一固定子网，应分别指定不同的网段。

修改子网需要重建 Docker 网络，仅用 `up --force-recreate` 不足以更新网络配置。已有环境按以下顺序操作，无需重新构建镜像；第一步使用尚未修改的原 Compose：

```bash
docker compose -f /data/ascend-runtime/compose.yaml down

python3 prepare_runtime.py \
  --image-ref-file /data/build/run-001/image-ref.txt \
  --code-dir /data/ascend-verify \
  --output-dir /data/ascend-runtime \
  --runtime-subnet 192.168.240.0/24

docker compose -f /data/ascend-runtime/compose.yaml config
docker compose -f /data/ascend-runtime/compose.yaml up -d
```

`down` 会停止本项目容器并移除其网络；验证目录和绑定挂载的 HOME 仍保留。新环境可直接生成配置后启动。

## NPU 配置

默认检查并映射 `/dev/davinci0`、`/dev/davinci_manager`、`/dev/hisi_hdc`，读取各设备节点的实际 GID，去重后写入 `group_add`，不假定它们属于同一组。驱动库、DCMI 和安装信息只读挂载。不同服务器布局可以显式调整：

```bash
python3 /path/to/ascend_dev/prepare_runtime.py \
  --image-ref-file /data/build/run-001/image-ref.txt \
  --code-dir /data/operator-project \
  --output-dir /data/ascend-runtime \
  --device /dev/davinci1 \
  --device /dev/davinci_manager \
  --device /dev/hisi_hdc \
  --driver-root /opt/ascend-driver \
  --dcmi-dir /opt/dcmi
```

自定义驱动根目录应含 `lib64/` 和 `version.info`。生成的容器内目标仍为 `/usr/local/Ascend/driver/...` 和 `/usr/local/dcmi`。仿真目标不检查或挂载 NPU 设备/驱动，传入这类专用参数会报错。

`devices` 提供设备映射，`group_add` 提供组身份；设备本身仍须允许相应组访问，驱动库及安装信息也须可读。两者不能替代驱动的实际授权和兼容性要求。[Docker 设备访问](https://docs.docker.com/engine/containers/run/#runtime-privilege-and-linux-capabilities)

## 用户记录与文件权限

以下以普通 Linux rootful Docker、未启用 user namespace 重映射为前提。生成的 Compose 对两个目标统一使用 root（`0:0`），`docker compose ... exec ascend bash` 也默认以 root 运行。Linux bind mount 中新建的文件通常归 root 所有；需要宿主机普通用户编辑这些产物时，应调整具体产物的属主或显式使用 developer 身份执行文件操作。

生成器保留 developer 账号副本，供显式切换身份时使用。独立的 `ascender/accounts.py` 模块从目标镜像复制账号表，在副本中为所选非 root UID 写入用户名、主组和 `/workspace/home`，保留 root 等系统账号。副本只读挂载到容器 `/etc/passwd`、`/etc/group`，环境变量 HOME 同样指向 `/workspace/home`。已有的同 UID 记录被替换；用户名被其他 UID 占用时拒绝生成。

该过程只创建一个未启动的临时容器读取账号文件，随后删除；不执行镜像入口、不修改宿主机账号、不复制密码数据库，也不在容器入口做身份切换。需要以宿主机对应身份执行代码编辑等操作时，可使用以下命令；此会话使用 developer 权限，访问 NPU 的验证命令仍使用默认 root 会话：

```bash
docker compose -f /data/ascend-runtime/compose.yaml exec --user developer ascend bash
```

developer 账号的默认 UID/GID 与当前开发用户一致，无需为每人重建镜像。`--uid`、`--gid`、`--user` 仅控制该账号记录，不能覆盖 Compose 固定的 root 运行身份。显式使用该账号时，应自行确保其能写源码和生成的 HOME；脚本不对外部项目自动 chown，不以 `chmod 777` 处理权限。如果项目依赖宿主机附加组，可通过 `--group-add` 指定数字 GID；不会自动导入宿主机所有组。[Docker 附加组](https://docs.docker.com/engine/containers/run/#additional-groups)

## 更新与验证

修改镜像、代码目录、UID/GID、设备或组后重新执行生成命令，再执行：

```bash
docker compose -f /data/ascend-runtime/compose.yaml up -d --force-recreate
```

重新生成会替换配置和账号副本，保留代码及 HOME 内容；不要让多个开发者或不同环境共用同一输出目录。生成文件可检查和手动编辑，后续重新生成会覆盖这些配置编辑。已有文件 bind mount 保留旧 inode，因此账号文件更新后应重建运行中的容器。

已有配置需要重新生成，并用上述 `--force-recreate` 命令重建容器，root 配置才会生效。先运行 `config` 查看展开后的配置；启动后执行 `id`、`whoami`，应显示 UID/GID 为 0、用户名为 root，再确认 HOME、目录可写及宿主机产物属主。NPU 再验证最小设备运算；仿真再执行实际 CAModel 的最小测试。

镜像入口负责加载 CANN 和仿真环境。不要通过 Compose 覆盖 `entrypoint`；直接 `docker exec ... python3 ...` 时可使用 `/usr/local/bin/ascend-entrypoint` 包装。CAModel 日志、缓存和输出应写 HOME、项目输出目录或 `/tmp`；有安装树写入要求时需为具体子目录配置权限。

仿真镜像已经完成运行库替换、软链接及 `set_env.sh` 生成，进入 Bash 会自动加载，无需再执行 `init.sh`。可以检查默认环境及库搜索顺序：

```bash
docker compose -f /data/ascend-runtime/compose.yaml exec ascend bash -lc \
  'printf "ASCEND_DEVICE_ID=%s\nESL_HARDWARE_VERSION=%s\nESL_SOC_VERSION=%s\nLD_LIBRARY_PATH=%s\n" \
    "$ASCEND_DEVICE_ID" "$ESL_HARDWARE_VERSION" "$ESL_SOC_VERSION" "$LD_LIBRARY_PATH"'
```

默认前三项为 `0`、`0x1000`、匹配的型号字符串（例如 `Ascend950DT`），`LD_LIBRARY_PATH` 第一项应为实际 CAModel 库目录。`ESL_SOC_VERSION` 以构建时的 `--esl-soc-version` 为准，`ESL_HARDWARE_VERSION` 可通过 `--esl-hardware-version` 调整；修改初始化参数后需重建镜像，再使用新报告中的 `image-ref.txt` 重新生成配置并重建容器。

生成器要求本地 Docker context，挂载路径必须存在于本机。NFS、ACL、SELinux、rootless/userns-remap 的权限映射需按实际情况检查。[用户命名空间说明](https://docs.docker.com/engine/security/userns-remap/)

旧 Bash 入口和 `compose.env` 接口已移除，账号准备通过 Python 模块完成。生成器无需安装第三方 Python 包；需要 Python 3.9+ 和可访问的本地 Docker。

当前验证使用本地文件、Docker 替身和通用字符设备样本；真实 Docker/NPU/CAModel 的运行验收仍需在目标服务器完成。
