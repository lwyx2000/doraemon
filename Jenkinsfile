// Jenkinsfile for Doraemon QuantTerminal Pro Docker Deployment
pipeline {
    agent any

    environment {
        PROJECT_NAME = 'doraemon'
        WORKSPACE_DIR = "${WORKSPACE}"
        DEPLOY_SERVER = 'sos@192.168.3.53'
        DEPLOY_PATH = '/home/sos/apps/doraemon'
        SSH_CREDENTIALS_ID = 'sos'

        GIT_REPO = 'git@github.com:lwyx2000/doraemon.git'

        COMPOSE_PROJECT_NAME = 'doraemon'
    }

    parameters {
        string(name: 'GIT_BRANCH', defaultValue: 'master', description: 'Git 分支名称')
        string(name: 'GIT_REPO', defaultValue: '', description: 'Git 仓库地址 (留空用环境变量)')
        string(name: 'GIT_SUBDIR', defaultValue: '', description: '代码子目录 (可选)')
        booleanParam(name: 'SKIP_TESTS', defaultValue: false, description: '跳过健康检查')
        booleanParam(name: 'FORCE_REBUILD', defaultValue: false, description: '强制重新构建镜像 (--no-cache)')
        booleanParam(name: 'FORCE_PULL', defaultValue: true, description: '强制拉取最新 Git 代码')

        choice(name: 'DEPLOY_TARGET', choices: ['all', 'backend', 'frontend'], description: '部署目标: all=前后端都部署, backend=仅后端, frontend=仅前端')

        choice(name: 'DEPLOY_ACTION', choices: ['deploy', 'build-only', 'stop', 'restart'], description: '部署动作')
    }

    stages {
        stage('环境检查') {
            steps {
                script {
                    echo "========================================"
                    echo "Doraemon QuantTerminal Pro 部署流水线"
                    echo "========================================"
                    echo "部署目标: ${DEPLOY_SERVER}:${DEPLOY_PATH}"
                    echo "分支: ${params.GIT_BRANCH}"

                    withCredentials([sshUserPrivateKey(credentialsId: SSH_CREDENTIALS_ID, keyFileVariable: 'SSH_KEY')]) {
                        sh """
                            chmod 600 ${SSH_KEY}
                            ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${DEPLOY_SERVER} '
                                docker --version
                                docker-compose --version
                                ssh-keyscan github.com >> /home/sos/.ssh/known_hosts 2>/dev/null || true
                            '
                        """
                    }
                }
            }
        }

        stage('验证基础镜像') {
            when {
                expression { params.DEPLOY_ACTION in ['deploy', 'build-only'] }
            }
            steps {
                script {
                    echo ">>> 验证基础镜像是否存在"
                    def targetImages = []
                    if (params.DEPLOY_TARGET in ['all', 'backend']) {
                        targetImages << 'python:3.12-slim'
                    }
                    if (params.DEPLOY_TARGET in ['all', 'frontend']) {
                        targetImages << 'nginx:alpine'
                    }
                    def imagesStr = targetImages.join(' ')
                    withCredentials([sshUserPrivateKey(credentialsId: SSH_CREDENTIALS_ID, keyFileVariable: 'SSH_KEY')]) {
                        sh """
                            chmod 600 ${SSH_KEY}
                            ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${DEPLOY_SERVER} '
                                MISSING=""

                                for img in ${imagesStr}; do
                                    if docker image inspect \$img > /dev/null 2>&1; then
                                        echo "[OK] \$img"
                                    else
                                        echo "[缺失] \$img"
                                        MISSING="\$MISSING \$img"
                                    fi
                                done

                                if [ -n "\$MISSING" ]; then
                                    echo ""
                                    echo "错误: 以下基础镜像不存在:\$MISSING"
                                    echo "请先手动拉取镜像后再执行部署"
                                    exit 1
                                fi

                                echo ""
                                echo "所有基础镜像验证通过"
                            '
                        """
                    }
                }
            }
        }

        stage('宿主机拉取代码') {
            when {
                expression { params.DEPLOY_ACTION in ['deploy', 'build-only'] }
            }
            steps {
                script {
                    def repo = params.GIT_REPO ?: env.GIT_REPO

                    withCredentials([sshUserPrivateKey(credentialsId: SSH_CREDENTIALS_ID, keyFileVariable: 'SSH_KEY')]) {
                        sh """
                            chmod 600 ${SSH_KEY}
                            ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${DEPLOY_SERVER} 'mkdir -p ${DEPLOY_PATH}'
                        """

                        sh """
                            chmod 600 ${SSH_KEY}
                            ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${DEPLOY_SERVER} '''
                                rm -rf ${DEPLOY_PATH}
                                mkdir -p ${DEPLOY_PATH}
                                git clone ${repo} ${DEPLOY_PATH} -b ${params.GIT_BRANCH}
                            '''
                        """

                        // 上传配置文件
                        sh """
                            chmod 600 ${SSH_KEY}
                            scp -i ${SSH_KEY} -o StrictHostKeyChecking=no ${WORKSPACE_DIR}/docker-compose.yml ${DEPLOY_SERVER}:${DEPLOY_PATH}/
                            scp -i ${SSH_KEY} -o StrictHostKeyChecking=no ${WORKSPACE_DIR}/.env.example ${DEPLOY_SERVER}:${DEPLOY_PATH}/
                            scp -i ${SSH_KEY} -o StrictHostKeyChecking=no ${WORKSPACE_DIR}/backend/Dockerfile ${DEPLOY_SERVER}:${DEPLOY_PATH}/backend/
                            scp -i ${SSH_KEY} -o StrictHostKeyChecking=no ${WORKSPACE_DIR}/frontend/Dockerfile ${DEPLOY_SERVER}:${DEPLOY_PATH}/frontend/
                            scp -i ${SSH_KEY} -o StrictHostKeyChecking=no ${WORKSPACE_DIR}/frontend/nginx.conf ${DEPLOY_SERVER}:${DEPLOY_PATH}/frontend/
                        """
                    }
                }
            }
        }

        stage('构建 Docker 镜像') {
            when {
                expression { params.DEPLOY_ACTION in ['deploy', 'build-only'] }
            }
            steps {
                script {
                    echo ">>> 构建 Docker 镜像"
                    def buildArgs = params.FORCE_REBUILD ? '--no-cache' : ''
                    def buildTargets = ''
                    if (params.DEPLOY_TARGET == 'backend') {
                        buildTargets = 'backend'
                    } else if (params.DEPLOY_TARGET == 'frontend') {
                        buildTargets = 'frontend'
                    }
                    withCredentials([sshUserPrivateKey(credentialsId: SSH_CREDENTIALS_ID, keyFileVariable: 'SSH_KEY')]) {
                        sh """
                            chmod 600 ${SSH_KEY}
                            ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${DEPLOY_SERVER} '
                                cd ${DEPLOY_PATH}

                                # 创建 .env 文件（如果不存在）
                                if [ ! -f .env ]; then
                                    cp .env.example .env
                                    echo "已从 .env.example 创建 .env 文件"
                                fi

                                # 构建后端镜像
                                if [ "${params.DEPLOY_TARGET}" = "all" ] || [ "${params.DEPLOY_TARGET}" = "backend" ]; then
                                    echo "构建后端镜像..."
                                    docker-compose build ${buildArgs} backend
                                fi

                                # 宿主机构建前端（规避 docker 内 npm 装包卡死）
                                if [ "${params.DEPLOY_TARGET}" = "all" ] || [ "${params.DEPLOY_TARGET}" = "frontend" ]; then
                                    echo "在宿主机构建前端..."
                                    export PATH=/home/sos/.nvm/versions/node/v20.19.0/bin:\$PATH
                                    cd "${DEPLOY_PATH}/frontend"
                                    npm install --no-audit --no-fund
                                    npm run build
                                    cd "${DEPLOY_PATH}"

                                    echo "构建前端镜像..."
                                    docker-compose build ${buildArgs} frontend
                                fi
                            '
                        """
                    }
                }
            }
        }

        stage('启动服务') {
            when {
                expression { params.DEPLOY_ACTION == 'deploy' }
            }
            steps {
                script {
                    echo ">>> 启动 Docker 服务"
                    def upTargets = ''
                    if (params.DEPLOY_TARGET == 'backend') {
                        upTargets = 'backend frontend'
                    } else if (params.DEPLOY_TARGET == 'frontend') {
                        upTargets = 'frontend'
                    } else {
                        upTargets = 'backend frontend'
                    }
                    def downTargets = ''
                    if (params.DEPLOY_TARGET == 'backend') {
                        downTargets = 'backend frontend'
                    } else if (params.DEPLOY_TARGET == 'frontend') {
                        downTargets = 'frontend'
                    } else {
                        downTargets = 'backend frontend'
                    }
                    withCredentials([sshUserPrivateKey(credentialsId: SSH_CREDENTIALS_ID, keyFileVariable: 'SSH_KEY')]) {
                        sh """
                            chmod 600 ${SSH_KEY}
                            ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${DEPLOY_SERVER} '
                                cd ${DEPLOY_PATH}
                                docker-compose rm -f -s ${downTargets} || true
                                docker-compose up -d ${upTargets}
                                sleep 10
                                docker-compose ps
                            '
                        """
                    }
                }
            }
        }

        stage('健康检查') {
            when {
                expression { params.DEPLOY_ACTION == 'deploy' && !params.SKIP_TESTS }
            }
            steps {
                script {
                    echo ">>> 执行健康检查"
                    withCredentials([sshUserPrivateKey(credentialsId: SSH_CREDENTIALS_ID, keyFileVariable: 'SSH_KEY')]) {
                        sh """
                            chmod 600 ${SSH_KEY}
                            ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${DEPLOY_SERVER} '
                                echo "等待服务就绪..."
                                for i in \$(seq 1 30); do
                                    code=\$(curl -s -o /dev/null -w "%{http_code}" http://localhost:9080/ 2>/dev/null || echo "000")
                                    if [ "\$code" = "200" ]; then
                                        echo "健康检查通过: http://localhost:9080/ (status=\$code)"
                                        break
                                    fi
                                    echo "  等待服务就绪... \$i/30 (status=\$code)"
                                    sleep 2
                                done

                                if [ "\$code" != "200" ]; then
                                    echo "健康检查失败，最终状态码: \$code"
                                    exit 1
                                fi

                                echo "验证后端 API..."
                                api_code=\$(curl -s -o /dev/null -w "%{http_code}" http://localhost:9080/api/v1/ 2>/dev/null || echo "000")
                                echo "后端 API 状态: \$api_code"
                            '
                        """
                    }
                }
            }
        }

        stage('停止服务') {
            when {
                expression { params.DEPLOY_ACTION == 'stop' }
            }
            steps {
                script {
                    echo ">>> 停止 Docker 服务"
                    withCredentials([sshUserPrivateKey(credentialsId: SSH_CREDENTIALS_ID, keyFileVariable: 'SSH_KEY')]) {
                        sh """
                            chmod 600 ${SSH_KEY}
                            ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${DEPLOY_SERVER} 'cd ${DEPLOY_PATH} && docker-compose down'
                        """
                    }
                }
            }
        }

        stage('重启服务') {
            when {
                expression { params.DEPLOY_ACTION == 'restart' }
            }
            steps {
                script {
                    echo ">>> 重启 Docker 服务"
                    def restartTargets = ''
                    if (params.DEPLOY_TARGET == 'backend') {
                        restartTargets = 'backend frontend'
                    } else if (params.DEPLOY_TARGET == 'frontend') {
                        restartTargets = 'frontend'
                    } else {
                        restartTargets = 'backend frontend'
                    }
                    withCredentials([sshUserPrivateKey(credentialsId: SSH_CREDENTIALS_ID, keyFileVariable: 'SSH_KEY')]) {
                        sh """
                            chmod 600 ${SSH_KEY}
                            ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${DEPLOY_SERVER} '
                                cd ${DEPLOY_PATH}
                                docker-compose restart ${restartTargets}
                                sleep 10
                                docker-compose ps
                            '
                        """
                    }
                }
            }
        }
    }

    post {
        success {
            script {
                echo "部署成功! 访问地址: http://${DEPLOY_SERVER.split('@')[1]}:9080"
            }
        }
        failure {
            script {
                echo "部署失败! 查看日志..."
                withCredentials([sshUserPrivateKey(credentialsId: SSH_CREDENTIALS_ID, keyFileVariable: 'SSH_KEY')]) {
                    sh """
                        chmod 600 ${SSH_KEY}
                        ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no ${DEPLOY_SERVER} '
                            if [ -d "${DEPLOY_PATH}" ]; then
                                cd ${DEPLOY_PATH} && docker-compose logs --tail=50
                            else
                                echo "部署目录 ${DEPLOY_PATH} 不存在，跳过日志查看"
                            fi
                        ' || true
                    """
                }
            }
        }
        always {
            deleteDir()
        }
    }
}
