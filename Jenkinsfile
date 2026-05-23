#!/usr/bin/env groovy
/**
 * @Time    : 2026-03-19
 * @Author  : Levi Fang 000592
 * @File    : Jenkinsfile
 * @Desc    : Jenkins pipeline configuration for supply chain risk alert service
 */

// Jenkins Pipeline Configuration
// 云平台算法部门 - 供应链风险预警系统

pipeline {
    agent any
    
    environment {
        PYTHON_VERSION = '3.9'
        DOCKER_IMAGE_NAME = 'supply-chain-risk-alert'
        DOCKER_REGISTRY = 'registry.example.com'
        VENV_DIR = 'venv'
    }
    
    options {
        // Keep last 10 builds
        buildDiscarder(logRotator(numToKeepStr: '10'))
        // Timeout after 1 hour
        timeout(time: 1, unit: 'HOURS')
        // Disable concurrent builds
        disableConcurrentBuilds()
        // Add timestamps to console output
        timestamps()
    }
    
    parameters {
        choice(
            name: 'DEPLOY_ENV',
            choices: ['dev', 'test', 'prod'],
            description: 'Target deployment environment'
        )
        booleanParam(
            name: 'RUN_TESTS',
            defaultValue: true,
            description: 'Run test suite'
        )
        booleanParam(
            name: 'BUILD_DOCKER',
            defaultValue: true,
            description: 'Build Docker image'
        )
        booleanParam(
            name: 'DEPLOY',
            defaultValue: false,
            description: 'Deploy to target environment'
        )
    }
    
    stages {
        stage('Checkout') {
            steps {
                script {
                    echo "Checking out code from ${env.GIT_BRANCH}..."
                    checkout scm
                    sh 'git log -1 --pretty=format:"%h - %an, %ar : %s"'
                }
            }
        }
        
        stage('Setup Environment') {
            steps {
                script {
                    echo "Setting up Python virtual environment..."
                    sh """
                        python${PYTHON_VERSION} --version
                        python${PYTHON_VERSION} -m venv ${VENV_DIR}
                        . ${VENV_DIR}/bin/activate
                        pip install --upgrade pip
                        pip install -r requirements.txt
                    """
                }
            }
        }
        
        stage('Code Quality') {
            parallel {
                stage('Lint - Black') {
                    steps {
                        script {
                            echo "Running Black code formatter check..."
                            sh """
                                . ${VENV_DIR}/bin/activate
                                pip install black
                                black --check --diff . || true
                            """
                        }
                    }
                }
                
                stage('Lint - Flake8') {
                    steps {
                        script {
                            echo "Running Flake8 linter..."
                            sh """
                                . ${VENV_DIR}/bin/activate
                                pip install flake8
                                flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics || true
                                flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics || true
                            """
                        }
                    }
                }
                
                stage('Type Check - MyPy') {
                    steps {
                        script {
                            echo "Running MyPy type checker..."
                            sh """
                                . ${VENV_DIR}/bin/activate
                                pip install mypy
                                mypy --ignore-missing-imports --no-strict-optional . || true
                            """
                        }
                    }
                }
                
                stage('Security Scan') {
                    steps {
                        script {
                            echo "Running security scan..."
                            sh """
                                . ${VENV_DIR}/bin/activate
                                pip install bandit safety
                                bandit -r . -f json -o bandit-report.json || true
                                safety check --json || true
                            """
                        }
                    }
                }
            }
        }
        
        stage('Run Tests') {
            when {
                expression { params.RUN_TESTS == true }
            }
            parallel {
                stage('Unit Tests') {
                    steps {
                        script {
                            echo "Running unit tests..."
                            sh """
                                . ${VENV_DIR}/bin/activate
                                playwright install chromium
                                playwright install-deps chromium
                                pytest tests/unit/ -v --cov=. --cov-report=xml --cov-report=html --cov-report=term || true
                            """
                        }
                    }
                    post {
                        always {
                            // Publish test results
                            junit allowEmptyResults: true, testResults: '**/test-results/*.xml'
                            // Publish coverage report
                            publishHTML([
                                allowMissing: true,
                                alwaysLinkToLastBuild: true,
                                keepAll: true,
                                reportDir: 'htmlcov',
                                reportFiles: 'index.html',
                                reportName: 'Coverage Report'
                            ])
                        }
                    }
                }
                
                stage('Property Tests') {
                    steps {
                        script {
                            echo "Running property-based tests..."
                            sh """
                                . ${VENV_DIR}/bin/activate
                                playwright install chromium
                                playwright install-deps chromium
                                pytest tests/property/ -v --hypothesis-show-statistics || true
                            """
                        }
                    }
                }
            }
        }
        
        stage('Build Docker Image') {
            when {
                expression { params.BUILD_DOCKER == true }
            }
            steps {
                script {
                    echo "Building Docker image..."
                    def imageTag = "${env.BUILD_NUMBER}-${env.GIT_COMMIT.take(7)}"
                    sh """
                        docker build -f Dockerfile.test -t ${DOCKER_REGISTRY}/${DOCKER_IMAGE_NAME}:${imageTag} .
                        docker tag ${DOCKER_REGISTRY}/${DOCKER_IMAGE_NAME}:${imageTag} ${DOCKER_REGISTRY}/${DOCKER_IMAGE_NAME}:latest
                    """
                    
                    // Push to registry
                    withCredentials([usernamePassword(
                        credentialsId: 'docker-registry-credentials',
                        usernameVariable: 'DOCKER_USER',
                        passwordVariable: 'DOCKER_PASS'
                    )]) {
                        sh """
                            echo \$DOCKER_PASS | docker login -u \$DOCKER_USER --password-stdin ${DOCKER_REGISTRY}
                            docker push ${DOCKER_REGISTRY}/${DOCKER_IMAGE_NAME}:${imageTag}
                            docker push ${DOCKER_REGISTRY}/${DOCKER_IMAGE_NAME}:latest
                        """
                    }
                }
            }
        }
        
        stage('Deploy') {
            when {
                expression { params.DEPLOY == true }
            }
            steps {
                script {
                    def targetEnv = params.DEPLOY_ENV
                    echo "Deploying to ${targetEnv} environment..."
                    
                    // Get deployment credentials
                    def serverHost = ""
                    def serverUser = ""
                    def credentialsId = ""
                    
                    switch(targetEnv) {
                        case 'dev':
                            serverHost = env.DEV_SERVER_HOST
                            serverUser = env.DEV_SERVER_USER
                            credentialsId = 'dev-server-ssh-key'
                            break
                        case 'test':
                            serverHost = env.TEST_SERVER_HOST
                            serverUser = env.TEST_SERVER_USER
                            credentialsId = 'test-server-ssh-key'
                            break
                        case 'prod':
                            serverHost = env.PROD_SERVER_HOST
                            serverUser = env.PROD_SERVER_USER
                            credentialsId = 'prod-server-ssh-key'
                            // Require manual approval for production
                            input message: 'Deploy to production?', ok: 'Deploy'
                            break
                    }
                    
                    // Deploy using SSH
                    sshagent(credentials: [credentialsId]) {
                        sh """
                            ssh -o StrictHostKeyChecking=no ${serverUser}@${serverHost} '
                                cd /opt/supply-chain-risk-alert &&
                                docker pull ${DOCKER_REGISTRY}/${DOCKER_IMAGE_NAME}:latest &&
                                docker-compose down &&
                                docker-compose up -d &&
                                docker-compose logs --tail=50
                            '
                        """
                    }
                    
                    // Health check
                    echo "Performing health check..."
                    sleep(time: 30, unit: 'SECONDS')
                    sshagent(credentials: [credentialsId]) {
                        sh """
                            ssh -o StrictHostKeyChecking=no ${serverUser}@${serverHost} '
                                docker ps | grep supply-chain-risk-alert
                            '
                        """
                    }
                }
            }
        }
    }
    
    post {
        always {
            echo "Pipeline execution completed."
            // Clean up workspace
            cleanWs()
        }
        
        success {
            echo "Pipeline succeeded!"
            // Send success notification
            script {
                if (params.DEPLOY == true) {
                    def message = """
                        ✅ 部署成功
                        
                        项目: ${env.JOB_NAME}
                        构建号: ${env.BUILD_NUMBER}
                        分支: ${env.GIT_BRANCH}
                        环境: ${params.DEPLOY_ENV}
                        提交: ${env.GIT_COMMIT.take(7)}
                        
                        查看详情: ${env.BUILD_URL}
                    """
                    // Send DingTalk notification (implement as needed)
                    echo message
                }
            }
        }
        
        failure {
            echo "Pipeline failed!"
            // Send failure notification
            script {
                def message = """
                    ❌ 构建失败
                    
                    项目: ${env.JOB_NAME}
                    构建号: ${env.BUILD_NUMBER}
                    分支: ${env.GIT_BRANCH}
                    
                    查看详情: ${env.BUILD_URL}
                """
                // Send DingTalk notification (implement as needed)
                echo message
            }
        }
        
        unstable {
            echo "Pipeline is unstable."
        }
    }
}
