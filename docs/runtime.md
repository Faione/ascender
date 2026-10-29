# 外部代码验证与 Compose 配置生成

运行前使用 `examples/prepare-runtime.sh`，一次生成具有具体镜像、UID/GID、路径和设备组的 `compose.yaml`。日常 Compose 命令无需逐项 export，也不需要 `.env` 或 `--env-file`。镜像构建工具仍只负责制作镜像，准备脚本只生成配置，不启动业务容器。

## 最小使用流程

在目标 Docker 服务器上，以拥有待验证代码的普通开发用户执行。将下面路径替换为真实路径：

```bash
bash /path/to/ascend_dev/examples/prepare-runtime.sh \
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

## 参数

| 参数 | 默认值或要求 |
| --- | --- |
| `--image-ref-file FILE` | 必填，构建报告中的单行镜像引用 |
| `--code-dir DIR` | 必填，已存在、可读写的外部代码目录 |
| `--output-dir DIR` | 必填，生成配置、账号文件和 HOME 的目录 |
| `--target npu\|simulation` | 默认读取镜像标签 |
| `--uid ID`、`--gid ID` | 默认 `id -u`、`id -g`，UID 必须非零 |
| `--user NAME` | 默认 `developer` |
| `--group-add GID` | 可重复，增加共享项目等所需的补充组 |
| `--device FILE` | NPU 专用，可重复；显式指定后替代默认设备清单 |
| `--driver-root DIR` | NPU 专用，默认 `/usr/local/Ascend/driver` |
| `--dcmi-dir DIR` | NPU 专用，默认 `/usr/local/dcmi` |
| `--install-info FILE` | NPU 专用，默认 `/etc/ascend_install.info` |

准备脚本只读取命令行和自身默认值，不继承旧的 `LOCAL_*`、`ASCEND_IMAGE`、`NPU_*_GID` 等配置变量。相对路径以调用目录为基准，生成配置使用绝对路径；可以从任意目录通过 `-f` 使用。

## NPU 配置

默认检查并映射 `/dev/davinci0`、`/dev/davinci_manager`、`/dev/hisi_hdc`，读取各设备节点的实际 GID，去重后写入 `group_add`，不假定它们属于同一组。驱动库、DCMI 和安装信息只读挂载。不同服务器布局可以显式调整：

```bash
bash /path/to/ascend_dev/examples/prepare-runtime.sh \
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

以下以普通 Linux rootful Docker、未启用 user namespace 重映射为前提。UID/GID 决定挂载代码的权限和新建产物属主。仅指定数字身份时，若容器缺少用户记录，Bash 会出现 `I have no name!`，用户查询也可能失败。[passwd 说明](https://man7.org/linux/man-pages/man5/passwd.5.html)

生成器调用底层 `prepare-user.sh`，从目标镜像复制账号表，在副本中为所选 UID 写入用户名、主组和 `/workspace/home`，保留其他系统账号。副本只读挂载到容器 `/etc/passwd`、`/etc/group`，环境变量 HOME 同样指向 `/workspace/home`。已有的同 UID 记录被替换；用户名被其他 UID 占用时拒绝生成。

该过程只创建一个未启动的临时容器读取账号文件，随后删除；不执行镜像入口、不修改宿主机账号、不复制密码数据库，也不在容器入口运行 root 初始化或身份切换。普通 `docker compose ... exec ascend bash` 即使用匹配 UID/GID 和完整用户名记录。

默认 UID/GID 与当前开发用户一致，无需为每人重建镜像。显式覆盖身份时，应自行确保该身份能写源码和生成的 HOME；脚本不对外部项目自动 chown，不以 `chmod 777` 处理权限。如果项目依赖宿主机附加组，可通过 `--group-add` 指定数字 GID；不会自动导入宿主机所有组。[Docker 附加组](https://docs.docker.com/engine/containers/run/#additional-groups)

## 更新与验证

修改镜像、代码目录、UID/GID、设备或组后重新执行生成命令，再执行：

```bash
docker compose -f /data/ascend-runtime/compose.yaml up -d --force-recreate
```

重新生成会替换配置和账号副本，保留代码及 HOME 内容；不要让多个开发者或不同环境共用同一输出目录。生成文件可检查和手动编辑，后续重新生成会覆盖这些配置编辑。已有文件 bind mount 保留旧 inode，因此账号文件更新后应重建运行中的容器。

先运行 `config` 查看展开后的配置；启动后执行 `id`、`whoami`、`getent passwd "$(id -u)"`，确认用户名和 HOME，检查目录可写及宿主机产物属主。NPU 再验证最小设备运算；仿真再执行实际 CAModel 的最小测试。

镜像入口负责加载 CANN 和仿真环境。不要通过 Compose 覆盖 `entrypoint`；直接 `docker exec ... python3 ...` 时可使用 `/usr/local/bin/ascend-entrypoint` 包装。CAModel 日志、缓存和输出应写 HOME、项目输出目录或 `/tmp`；有安装树写入要求时需为具体子目录配置权限。

NFS、ACL、SELinux、rootless/userns-remap 的权限映射需按实际情况检查；使用远程 Docker 时，路径必须存在于 daemon 所在服务器。[用户命名空间说明](https://docs.docker.com/engine/security/userns-remap/)

底层 `prepare-user.sh` 保留原有环境变量接口和 `compose.env` 输出，供单独准备账号的已有流程使用；新生成流程不发布或依赖该环境文件。原有两份环境变量 Compose 模板由生成的单份 `compose.yaml` 替代。

当前验证使用本地文件、Docker 替身和通用字符设备样本；真实 Docker/NPU/CAModel 的运行验收仍需在目标服务器完成。
