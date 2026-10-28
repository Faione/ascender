# 外部代码挂载与 Compose 运行说明

本文及 `examples/compose*.yaml` 是运行参考，不扩展镜像构建工具的职责。首版工具已实现；真实镜像及设备尚未验收，示例须在镜像已构建、目标服务器条件满足后使用。

## 权限约定

以下以普通 Linux rootful Docker、未启用 user namespace 重映射为前提。源码和产物权限取决于数字 UID/GID 以及目录权限、ACL，不要求宿主机与容器用户名相同。镜像默认 root 时，以 root 在可写源码挂载中构建，会使新建产物通常归宿主机 root 所有。

Compose 使用 `user: "${LOCAL_UID}:${LOCAL_GID}"` 指定宿主机开发用户身份，不必为每位开发者重建镜像。仅指定数字身份还不够：容器 `/etc/passwd` 中没有该 UID 时，Bash 可能显示 `I have no name!`，Python 的 `pwd.getpwuid()` 等查询也可能失败。设置 `USER`、`PS1` 或 `HOME` 不能补齐用户数据库。[Docker 用户选项](https://docs.docker.com/engine/containers/run/#user)、[passwd 文件含义](https://man7.org/linux/man-pages/man5/passwd.5.html)

使用 `examples/prepare-user.sh` 从所选镜像复制账号文件，在副本中补充 UID/GID 和 `/workspace/home`，由 Compose 只读挂载到 `/etc/passwd`、`/etc/group`。镜像其他系统账号保留；该 UID 已存在时默认复用其用户名，否则使用 `ascend-<UID>`。可用 `LOCAL_USER` 明确指定用户名，若与其他 UID 冲突则报错。主组有对应 GID 时复用组名，否则添加 `ascend-<GID>`。

此脚本不读取或修改宿主机 `/etc/passwd`、`/etc/group`，不挂载宿主机账号库，也不处理密码认证或 shadow。它只创建一个未启动的临时容器读取目标镜像文件，完成后删除；不执行镜像入口。容器启动后直接以所选数字身份运行，普通 `docker compose exec ... bash` 无需再经过 root 初始化/降权。

匹配身份并不授予额外权限：宿主机用户本身应能读取源码及遍历目录，且可写构建输出位置。若依赖共享项目组，则在 `group_add` 中追加该组的数字 GID；指定 UID/GID 不会自动复制宿主机所有附加组。NFS、ACL、SELinux 及 rootless/userns-remap 环境须根据实际映射另行检查。[Docker 附加组](https://docs.docker.com/engine/containers/run/#additional-groups)、[用户命名空间限制](https://docs.docker.com/engine/security/userns-remap/)

## 通用配置

`examples/compose.yaml` 对 NPU 与仿真共用：

- `image` 从构建输出的 `image-ref.txt` 读取后传入；这是选择已有镜像，不能用于自定义构建 tag。保留 `pull_policy: never`，不配置 `build`。
- 将任意外部代码目录映射到固定的 `/workspace/code`，不再绑定参考仓库的 `examples/add_pipeline`。
- 使用宿主机 UID/GID，源码默认可写，兼容会在项目内生成 `build/`、扩展模块等文件的构建方式。
- 使用准备好的容器账号副本，保证用户名、主组和 HOME 的查询一致；不会用宿主机账号库替换镜像系统账号。
- 将单独的宿主机可写目录挂为 `/workspace/home`，显式设置 HOME 和缓存根目录，避免程序尝试写入 `/root`。
- 使用长格式 bind mount 和 `create_host_path: false`；挂载路径拼错或不存在时报错，不由 Docker 创建错误目录。
- 保留镜像入口，不覆盖 `entrypoint`，保证 CANN/仿真环境加载。

Compose 的 `user`、`group_add` 和长格式挂载选项见[服务配置文档](https://docs.docker.com/reference/compose-file/services/)。Bind mount 将遮蔽目标目录的原有内容，因此只挂载工作目录，不用源码覆盖 CANN 或 `/opt/CAModel` 安装目录。[Bind mount 说明](https://docs.docker.com/engine/storage/bind-mounts/)

在目标 Docker 服务器上，以拥有代码目录的普通开发用户准备变量。先将 `COMPOSE_DIR`、`CODE_DIR` 和镜像引用文件路径替换为真实绝对路径：

```bash
export COMPOSE_DIR=/path/to/ascend_dev/examples
export CODE_DIR=/path/to/operator-project
export DEV_HOME="${CODE_DIR}/.ascend-dev-home"
export LOCAL_UID="$(id -u)"
export LOCAL_GID="$(id -g)"
export ASCEND_IMAGE="$(cat /path/to/build/build-id/image-ref.txt)"
export IDENTITY_DIR="${DEV_HOME}/.ascend-identity"

test -d "$CODE_DIR" && test -r "$CODE_DIR" && test -w "$CODE_DIR"
mkdir -p "$DEV_HOME"
bash "$COMPOSE_DIR/prepare-user.sh"
```

这些是用户手动执行的准备步骤，不由构建脚本管理。`LOCAL_UID` 必须非零；不要用 sudo 改变准备过程的开发用户身份。`DEV_HOME` 可放到代码仓库外的已有目录；示例将其放到项目中，便于理解，需要时加入该项目的忽略规则。使用远程 Docker 时，挂载路径必须存在于 daemon 所在服务器，而非仅存在于本地客户端。

更换镜像、UID/GID 或用户名后，重新执行准备脚本，再用 `docker compose ... up -d --force-recreate` 重建使用中的容器；已有文件 bind mount 不会自动切换到新发布文件的 inode。为不同镜像或不同开发者使用独立的 `IDENTITY_DIR`，避免互相覆盖账号副本。

仿真环境选择构建出的 `ascend-sim:...` 镜像，仅使用通用配置：

```bash
docker compose -f "$COMPOSE_DIR/compose.yaml" config
docker compose -f "$COMPOSE_DIR/compose.yaml" up -d
docker compose -f "$COMPOSE_DIR/compose.yaml" exec ascend bash
```

通用配置不挂 NPU 设备。实际仿真软件若另有运行条件，按供应方要求补充，不从 NPU 配置复制设备和驱动挂载。

## NPU 补充配置

`examples/compose.npu.yaml` 叠加设备、设备组和只读驱动挂载，沿用参考资料的路径。先检查服务器实际布局；三类设备可能属于不同的组，不能统一假定是某个固定 GID。

```bash
ls -ln /dev/davinci0 /dev/davinci_manager /dev/hisi_hdc
export NPU_DEVICE_GID="$(stat -c '%g' /dev/davinci0)"
export NPU_MANAGER_GID="$(stat -c '%g' /dev/davinci_manager)"
export NPU_HDC_GID="$(stat -c '%g' /dev/hisi_hdc)"
```

选择构建出的 `ascend-dev:...` 镜像，并保持同样的两个文件参数：

```bash
docker compose -f "$COMPOSE_DIR/compose.yaml" -f "$COMPOSE_DIR/compose.npu.yaml" config
docker compose -f "$COMPOSE_DIR/compose.yaml" -f "$COMPOSE_DIR/compose.npu.yaml" up -d
docker compose -f "$COMPOSE_DIR/compose.yaml" -f "$COMPOSE_DIR/compose.npu.yaml" exec ascend bash
```

`devices` 解决设备映射，`group_add` 解决组身份，二者不能相互替代。设备文件仍须允许对应组访问；驱动库和安装信息也须能被所选用户读取。存在驱动专用授权、ACL 或其他限制时，应遵循该服务器驱动的要求，不能仅凭添加 GID 宣称 NPU 可用。[Docker 设备访问](https://docs.docker.com/engine/containers/run/#runtime-privilege-and-linux-capabilities)

这里没有默认添加 `privileged: true`，也不通过 `chmod 777`、关闭文件权限或在入口递归 chown 代码目录处理问题。若现有目录已含 root 产物，应确认具体输出范围后由所有者/管理员修复，不对整个外部项目自动修改属主。

## 镜像需要配合的事项

1. 构建阶段仍使用 root 安装；运行阶段支持 Compose 传入任意数字 UID/GID，不在镜像中固定宿主机账号。
2. 入口仅加载环境并执行命令，不要求 root，不运行 useradd、chown、运行期安装依赖等操作。
3. CANN、Torch 和仿真程序的必要文件对运行用户可读、可执行；构建时验证，避免依赖 root 专属的 Python 用户安装目录或缓存。
4. 源码和缓存位于独立挂载目录；CAModel 日志、临时文件和编译输出优先写 HOME、项目输出目录或 `/tmp`。若某个 CAModel 必须写安装树，应只为明确的可写子目录设计权限/挂载，不能假定整个 `/opt/CAModel` 可写。
5. Compose 的账号副本将 passwd HOME 与环境变量 HOME 对齐。仅设置环境变量不够，必须先执行准备脚本；镜像安装权限通过不代表任意 CAModel 已完成非 root 运行验收。

## 可选的只读源码方案

若项目支持源码外构建，可将代码挂载设为 `read_only: true`，另挂载由开发用户预先创建的可写输出目录，如 `/workspace/build`。例如 CMake 可使用 `cmake -S /workspace/code -B /workspace/build`；其他项目需使用其对应的构建方式，不能仅修改 Compose 就假设它支持源码外构建。

当前参考算子采用项目内构建，因此默认示例保留代码可写，并通过 UID/GID 保证产物归属。代码目录已有写权限时无需修改宿主机权限。

## 使用前验证

先执行 `docker compose ... config` 检查配置展开；启动后执行 `id`、`whoami`、`getent passwd "$(id -u)"`，确认用户名存在、passwd 中的 HOME 为 `/workspace/home`，再检查 HOME 可写，并在源码目录创建再删除一个临时测试文件，核对宿主机看到的 UID/GID。NPU 再单独检查设备和最小运算；仿真执行该 CAModel 的最小验证。

当前示例尚未在实际 Docker/NPU/CAModel 环境运行验证，设备及驱动路径是参考布局，不是所有型号的固定要求。
