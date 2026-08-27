# 内网 GitLab 克隆推送计划

> 目标：将本仓库（GitHub 公网托管）完整同步到内网 GitLab，并建立后续增量同步流程。
> 内网环境无法访问 GitHub，采用 **git bundle** 文件离线传输方式。

## 一、前置检查（开发机）

```bash
# 1. 确认工作区干净、所有提交已推送到 GitHub
git status
git log origin/main..main          # 为空则已全部推送

# 2. 确认敏感文件不在版本库中（secret.key / 打包产物均已 gitignore）
git ls-files | grep -E "secret.key|tar.gz|\.so$"    # 应无输出
git count-objects -vH               # 查看仓库体积, 确认无大文件误入库
```

## 二、开发机（外网）打包完整历史

```bash
# 打包全部分支与标签(含完整历史)
git bundle create future_email_data_statement.bundle --all

# 校验包完整性
git bundle verify future_email_data_statement.bundle
# 应输出: future_email_data_statement.bundle is okay
```

## 三、传输到内网机器

任选其一：

```bash
# 方式 A: 内网共享盘 / 跳板机中转
cp future_email_data_statement.bundle /mnt/share/
scp future_email_data_statement.bundle user@内网服务器:/home/user/

# 方式 B: U 盘 / 邮件(体积大时压缩)
gzip future_email_data_statement.bundle
```

## 四、内网机器克隆并推送到 GitLab

```bash
# 0. 环境准备(若内网机器无 git)
sudo yum install -y git

# 1. 从 bundle 克隆出完整仓库(历史/分支/标签齐全)
git clone future_email_data_statement.bundle future_email_data_statement
cd future_email_data_statement

# 2. 内网 GitLab 新建**空**项目(不要勾选初始化 README, 避免默认分支冲突)

# 3. 添加内网 GitLab 远程并推送
git remote add gitlab http://gitlab.内网域名/组名/future_email_data_statement.git
git push -u gitlab --all       # 推送全部分支
git push gitlab --tags         # 推送全部标签

# 4. 验证
git remote -v                  # origin(可选, 内网可保留指向 GitHub 或删除) + gitlab
```

> 若 GitLab 项目已自动创建了 README/main 分支导致推送冲突，用
> `git push -u gitlab --all --force` 覆盖（确保仓库内容正确后）。

## 五、后续增量同步

每次外网有更新后，重复"打包 → 传输 → 内网拉取"：

```bash
# 开发机(外网): 只打包相对上次同步点的增量
git bundle create update.bundle main@{1}..main   # 或记录上次同步的 commit hash 代替 main@{1}
# 打包前确认: git log main@{1}..main --oneline 为本次需要同步的提交

# 内网机器:
git fetch update.bundle
git merge FETCH_HEAD            # 或 git pull update.bundle main
git push gitlab --all           # 推送到内网 GitLab
```

> 也可直接用 `git format-patch` 生成补丁系列传输，但 bundle 保留提交历史与分支关系，推荐 bundle。

## 六、部署内网生产环境（同步完成后的打包发布）

内网机器上使用与开发机相同的 Python 3.11 + PDM 环境：

```bash
# 1. 安装依赖
pdm install -G dev              # dev 组含 cython/pyinstaller 打包工具
                                # 生产编译机需已安装 gcc

# 2. 一键打包(.so 编译 + PyInstaller + 发布包组装)
pdm run python pyinstall.py

# 产物:
#   future_email_data_statement_tree.tar.gz              完整部署包(可执行程序 + src .so + config 模板)
#   future_email_data_statement_config_template.tar.gz   config 模板包

# 3. 部署目录初始化
mkdir -p /opt/future_email_data_statement && cd /opt/future_email_data_statement
tar -xzf future_email_data_statement_tree.tar.gz
cd future_email_data_statement_deploy
#    a) 填写 config/info.ini(数据库/文件目录, Place) 与 config/email.json(邮箱)
#    b) 生成加密密钥与密文:
python -m src.future_email_data_statement.common.generate_key
python -m src.future_email_data_statement.common.generate_password <明文密码>

# 4. 运行(参数风格同 auto_down_email)
./future_email_data_statement 20260826 today
./future_email_data_statement 20260826 last download_and_unzip
```

## 七、注意事项

| 事项 | 说明 |
|------|------|
| 敏感信息 | `config/secret.key`、真实数据库/邮箱凭据不入库（.gitignore 已排除），bundle 不会携带 |
| 打包产物 | `dist/`、`*.tar.gz`、`*_deploy/`、`*.so` 均不入库，仅在部署机器上生成 |
| 首次推送冲突 | GitLab 空项目初始化 README 时，用 `--force` 覆盖推送 |
| 换机传输 | bundle 文件校验通过后再克隆；传输后建议 `git fsck` 检查 |
| 分支策略 | 内网 GitLab 为主干 `main` 只读镜像，修改一律回到 GitHub 端 |

## 八、命令速查

```bash
git bundle create repo.bundle --all        # 全量打包
git bundle verify repo.bundle              # 校验
git clone repo.bundle dir                  # bundle 克隆
git bundle create upd.bundle old..new      # 增量打包
git fetch upd.bundle && git merge FETCH_HEAD   # 内网增量合并
```
