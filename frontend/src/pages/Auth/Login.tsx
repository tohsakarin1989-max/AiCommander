import { useState } from 'react'
import { Alert, Button, Form, Input } from 'antd'
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons'
import { useAuth } from '../../auth/AuthContext'
import type { UserCreatePayload } from '../../services/auth'
import './Login.css'

interface LoginFormValues {
  username: string
  password: string
  display_name?: string
  confirm_password?: string
  bootstrap_token?: string
}

export default function Login() {
  const { phase, bootstrapAvailable, localBootstrapAvailable, login, bootstrap } = useAuth()
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const isBootstrap = phase === 'bootstrap'
  const canBootstrap = localBootstrapAvailable || bootstrapAvailable

  const submit = async (values: LoginFormValues) => {
    setError('')
    setSubmitting(true)
    try {
      if (isBootstrap) {
        const payload: UserCreatePayload = {
          username: values.username,
          display_name: values.display_name,
          password: values.password,
          role: 'admin',
        }
        await bootstrap(payload, values.bootstrap_token || '')
      } else {
        await login(values.username, values.password)
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '操作失败，请稍后重试'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  if (phase === 'loading') {
    return (
      <div className="auth-screen auth-loading" role="status">
        <div className="auth-loader" />
        <span>正在校验系统状态</span>
      </div>
    )
  }

  return (
    <div className="auth-screen">
      <section className="auth-context" aria-label="系统信息">
        <div className="auth-brand-mark">AiC</div>
        <div>
          <div className="auth-kicker">AICOMMANDER / SECURE ACCESS</div>
          <h1>涉油案件数智研判系统</h1>
          <p>案件资料、研判结论与模型配置均属于受控数据。系统将记录登录和业务写操作。</p>
        </div>
        <dl className="auth-facts">
          <div><dt>访问域</dt><dd>单位内网 / VPN</dd></div>
          <div><dt>会话保护</dt><dd>HttpOnly · SameSite</dd></div>
          <div><dt>审计状态</dt><dd>已启用</dd></div>
        </dl>
      </section>

      <main className="auth-panel">
        <div className="auth-panel-head">
          <SafetyCertificateOutlined />
          <div>
            <h2>{isBootstrap ? '初始化系统管理员' : '身份验证'}</h2>
            <p>{isBootstrap ? '仅在首次部署时执行一次' : '使用分配的账号进入研判工作台'}</p>
          </div>
        </div>

        {isBootstrap && localBootstrapAvailable && (
          <Alert
            type="info"
            showIcon
            message="本机首次初始化"
            description="当前为本机测试环境，可直接创建首位管理员；正式部署时此入口会自动关闭。"
          />
        )}
        {isBootstrap && !canBootstrap && (
          <Alert
            type="warning"
            showIcon
            message="服务器尚未配置初始化凭据"
            description="请先在生产环境变量中设置一次性 BOOTSTRAP_TOKEN，再刷新本页。"
          />
        )}
        {error && <Alert type="error" showIcon message={error} />}

        <Form<LoginFormValues>
          layout="vertical"
          requiredMark={false}
          onFinish={submit}
          autoComplete="off"
        >
          {isBootstrap && (
            <>
              {!localBootstrapAvailable && (
                <Form.Item
                  label="一次性初始化令牌"
                  name="bootstrap_token"
                  rules={[{ required: true, message: '请输入服务器初始化令牌' }]}
                >
                  <Input.Password prefix={<LockOutlined />} autoComplete="off" />
                </Form.Item>
              )}
              <Form.Item label="显示名称" name="display_name">
                <Input placeholder="例如：系统管理员" maxLength={100} />
              </Form.Item>
            </>
          )}
          <Form.Item
            label="用户名"
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserOutlined />} autoComplete="username" maxLength={64} />
          </Form.Item>
          <Form.Item
            label="密码"
            name="password"
            rules={[
              { required: true, message: '请输入密码' },
              ...(isBootstrap ? [{ min: 12, message: '密码至少 12 位' }] : []),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} autoComplete={isBootstrap ? 'new-password' : 'current-password'} />
          </Form.Item>
          {isBootstrap && (
            <Form.Item
              label="确认密码"
              name="confirm_password"
              dependencies={['password']}
              rules={[
                { required: true, message: '请再次输入密码' },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    return !value || getFieldValue('password') === value
                      ? Promise.resolve()
                      : Promise.reject(new Error('两次输入的密码不一致'))
                  },
                }),
              ]}
            >
              <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
            </Form.Item>
          )}
          <Button
            type="primary"
            htmlType="submit"
            block
            loading={submitting}
            disabled={isBootstrap && !canBootstrap}
          >
            {isBootstrap ? '创建管理员并进入系统' : '登录系统'}
          </Button>
        </Form>
        <div className="auth-panel-foot">连续 5 次登录失败将暂时锁定账号</div>
      </main>
    </div>
  )
}
