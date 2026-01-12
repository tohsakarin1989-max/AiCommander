import React, { useState } from 'react'
import {
  Card,
  Tabs,
  Table,
  Tag,
  Alert,
  List,
  Descriptions,
  Space,
  Button,
  InputNumber,
  Typography,
  Timeline,
  Statistic,
  Row,
  Col,
  Divider,
} from 'antd'
import {
  ClockCircleOutlined,
  AimOutlined,
  EnvironmentOutlined,
  TeamOutlined,
  SafetyOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { deploymentApi } from '../../services/deployment'

const { Title, Paragraph, Text } = Typography

const Deployment: React.FC = () => {
  const [analysisDays, setAnalysisDays] = useState(90)

  const { data: report, isLoading, refetch } = useQuery({
    queryKey: ['deploymentReport', analysisDays],
    queryFn: () => deploymentApi.getReport(analysisDays),
  })

  const { data: temporalPatterns } = useQuery({
    queryKey: ['temporalPatterns', analysisDays],
    queryFn: () => deploymentApi.getTemporalPatterns(analysisDays),
  })

  const { data: targetPatterns } = useQuery({
    queryKey: ['targetPatterns'],
    queryFn: () => deploymentApi.getTargetPatterns(),
  })

  const { data: patrolRoutes } = useQuery({
    queryKey: ['patrolRoutes'],
    queryFn: () => deploymentApi.getPatrolRoutes(),
  })

  const { data: resourceAllocation } = useQuery({
    queryKey: ['resourceAllocation'],
    queryFn: () => deploymentApi.getResourceAllocation(),
  })

  const { data: preventionMeasures } = useQuery({
    queryKey: ['preventionMeasures'],
    queryFn: () => deploymentApi.getPreventionMeasures(),
  })

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Title level={2}>工作部署建议</Title>
        <Space>
          <Text>分析周期：</Text>
          <InputNumber
            min={7}
            max={365}
            value={analysisDays}
            onChange={(value) => setAnalysisDays(value || 90)}
            addonAfter="天"
          />
          <Button icon={<ReloadOutlined />} onClick={() => refetch()}>
            刷新
          </Button>
        </Space>
      </div>

      <Alert
        message="工作部署建议说明"
        description={
          <div>
            <Paragraph>
              本功能基于<Text strong>已破获案件</Text>的历史数据，通过模式识别和数据分析，生成预防性的工作部署建议。
            </Paragraph>
            <Paragraph>
              <Text strong>核心思路：</Text>
            </Paragraph>
            <ul>
              <li>
                <Text strong>时间模式分析</Text>：识别案件高发时段、日期规律，指导巡逻时间安排
              </li>
              <li>
                <Text strong>空间模式分析</Text>：识别案件热点区域，优化巡逻路线和资源配置
              </li>
              <li>
                <Text strong>目标模式分析</Text>：识别高发目标类型，制定针对性防护措施
              </li>
              <li>
                <Text strong>预防措施建议</Text>：基于案件特征，提出具体的预防和防控措施
              </li>
            </ul>
            <Paragraph>
              <Text type="secondary">
                注意：这些建议基于历史数据，实际部署时需结合当前实际情况和资源条件。
              </Text>
            </Paragraph>
          </div>
        }
        type="info"
        style={{ marginBottom: 24 }}
      />

      {report?.summary && (
        <Card title="综合分析摘要" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col span={8}>
              <Statistic
                title="分析周期"
                value={report.summary.analysis_period}
                prefix={<ClockCircleOutlined />}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="关键发现"
                value={report.summary.key_findings.length}
                suffix="项"
                prefix={<FileTextOutlined />}
              />
            </Col>
            <Col span={8}>
              <Statistic
                title="优先行动"
                value={report.summary.priority_actions.length}
                suffix="项"
                prefix={<AimOutlined />}
              />
            </Col>
          </Row>
          <Divider />
          <Title level={4}>关键发现</Title>
          <List
            dataSource={report.summary.key_findings}
            renderItem={(item: string) => <List.Item>{item}</List.Item>}
          />
          <Title level={4} style={{ marginTop: 16 }}>
            优先行动建议
          </Title>
          <Timeline>
            {report.summary.priority_actions.map((action: string, index: number) => (
              <Timeline.Item key={index} color="red">
                {action}
              </Timeline.Item>
            ))}
          </Timeline>
        </Card>
      )}

      <Tabs
        defaultActiveKey="temporal"
        items={[
          {
            key: 'temporal',
            label: (
              <span>
                <ClockCircleOutlined /> 时间模式分析
              </span>
            ),
            children: (
              <Card>
                {temporalPatterns?.high_risk_hours ? (
                  <div>
                    <Title level={4}>高发时段分析</Title>
                    <Table
                      dataSource={temporalPatterns.high_risk_hours}
                      columns={[
                        { title: '时段', dataIndex: 'hour_range', key: 'hour_range' },
                        {
                          title: '案件数量',
                          dataIndex: 'case_count',
                          key: 'case_count',
                        },
                        {
                          title: '占比',
                          dataIndex: 'percentage',
                          key: 'percentage',
                          render: (val: number) => `${val}%`,
                        },
                      ]}
                      pagination={false}
                      size="small"
                    />
                    <Title level={4} style={{ marginTop: 24 }}>
                      高发日期分析
                    </Title>
                    <Table
                      dataSource={temporalPatterns.high_risk_weekdays}
                      columns={[
                        { title: '日期', dataIndex: 'weekday_name', key: 'weekday_name' },
                        {
                          title: '案件数量',
                          dataIndex: 'case_count',
                          key: 'case_count',
                        },
                        {
                          title: '占比',
                          dataIndex: 'percentage',
                          key: 'percentage',
                          render: (val: number) => `${val}%`,
                        },
                      ]}
                      pagination={false}
                      size="small"
                    />
                    <Alert
                      message="部署建议"
                      description={
                        <List
                          dataSource={temporalPatterns.recommendations}
                          renderItem={(item: string) => <List.Item>{item}</List.Item>}
                        />
                      }
                      type="info"
                      style={{ marginTop: 16 }}
                    />
                  </div>
                ) : (
                  <Alert message={temporalPatterns?.message || '暂无数据'} type="info" />
                )}
              </Card>
            ),
          },
          {
            key: 'target',
            label: (
              <span>
                <AimOutlined /> 目标模式分析
              </span>
            ),
            children: (
              <Card>
                {targetPatterns?.high_risk_case_types ? (
                  <div>
                    <Title level={4}>高发案件类型</Title>
                    <Table
                      dataSource={targetPatterns.high_risk_case_types}
                      columns={[
                        { title: '案件类型', dataIndex: 'type', key: 'type' },
                        {
                          title: '案件数量',
                          dataIndex: 'count',
                          key: 'count',
                        },
                        {
                          title: '占比',
                          dataIndex: 'percentage',
                          key: 'percentage',
                          render: (val: number) => `${val}%`,
                        },
                      ]}
                      pagination={false}
                      size="small"
                    />
                    {targetPatterns.high_risk_facilities && (
                      <>
                        <Title level={4} style={{ marginTop: 24 }}>
                          高发设施类型
                        </Title>
                        <Table
                          dataSource={targetPatterns.high_risk_facilities}
                          columns={[
                            {
                              title: '设施类型',
                              dataIndex: 'facility_type',
                              key: 'facility_type',
                            },
                            {
                              title: '案件数量',
                              dataIndex: 'count',
                              key: 'count',
                            },
                            {
                              title: '占比',
                              dataIndex: 'percentage',
                              key: 'percentage',
                              render: (val: number) => `${val}%`,
                            },
                          ]}
                          pagination={false}
                          size="small"
                        />
                      </>
                    )}
                    <Alert
                      message="部署建议"
                      description={
                        <List
                          dataSource={targetPatterns.recommendations}
                          renderItem={(item: string) => <List.Item>{item}</List.Item>}
                        />
                      }
                      type="info"
                      style={{ marginTop: 16 }}
                    />
                  </div>
                ) : (
                  <Alert message={targetPatterns?.message || '暂无数据'} type="info" />
                )}
              </Card>
            ),
          },
          {
            key: 'routes',
            label: (
              <span>
                <EnvironmentOutlined /> 巡逻路线建议
              </span>
            ),
            children: (
              <Card>
                {patrolRoutes?.routes && patrolRoutes.routes.length > 0 ? (
                  <div>
                    <List
                      dataSource={patrolRoutes.routes}
                      renderItem={(route: any) => (
                        <List.Item>
                          <Card style={{ width: '100%' }}>
                            <Descriptions column={2} size="small">
                              <Descriptions.Item label="路线名称">
                                {route.route_name}
                              </Descriptions.Item>
                              <Descriptions.Item label="优先级">
                                <Tag color={route.priority === '高' ? 'red' : 'orange'}>
                                  {route.priority}
                                </Tag>
                              </Descriptions.Item>
                              <Descriptions.Item label="中心位置">
                                {route.center_latitude.toFixed(6)},{' '}
                                {route.center_longitude.toFixed(6)}
                              </Descriptions.Item>
                              <Descriptions.Item label="案件数量">
                                {route.case_count} 起
                              </Descriptions.Item>
                              <Descriptions.Item label="覆盖半径">
                                {route.coverage_radius_km} 公里
                              </Descriptions.Item>
                            </Descriptions>
                            <div style={{ marginTop: 8 }}>
                              <Text strong>建议巡逻时段：</Text>
                              <Space wrap style={{ marginTop: 4 }}>
                                {route.recommended_patrol_times.map((time: string) => (
                                  <Tag key={time}>{time}</Tag>
                                ))}
                              </Space>
                            </div>
                            <Alert
                              message="路线建议"
                              description={
                                <List
                                  dataSource={route.suggestions}
                                  renderItem={(item: string) => (
                                    <List.Item style={{ padding: '4px 0' }}>{item}</List.Item>
                                  )}
                                />
                              }
                              type="info"
                              style={{ marginTop: 8 }}
                            />
                          </Card>
                        </List.Item>
                      )}
                    />
                    <Alert
                      message="总体建议"
                      description={
                        <List
                          dataSource={patrolRoutes.recommendations}
                          renderItem={(item: string) => <List.Item>{item}</List.Item>}
                        />
                      }
                      type="success"
                      style={{ marginTop: 16 }}
                    />
                  </div>
                ) : (
                  <Alert message={patrolRoutes?.message || '暂无数据'} type="info" />
                )}
              </Card>
            ),
          },
          {
            key: 'resources',
            label: (
              <span>
                <TeamOutlined /> 资源配置建议
              </span>
            ),
            children: (
              <Card>
                {resourceAllocation?.resource_suggestions ? (
                  <div>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={8}>
                        <Statistic
                          title="热点区域总数"
                          value={resourceAllocation.total_hotspots}
                          prefix={<EnvironmentOutlined />}
                        />
                      </Col>
                      <Col span={8}>
                        <Statistic
                          title="高优先级区域"
                          value={resourceAllocation.high_priority_areas}
                          prefix={<AimOutlined />}
                          valueStyle={{ color: '#cf1322' }}
                        />
                      </Col>
                      <Col span={8}>
                        <Statistic
                          title="中优先级区域"
                          value={resourceAllocation.medium_priority_areas}
                          prefix={<AimOutlined />}
                          valueStyle={{ color: '#fa8c16' }}
                        />
                      </Col>
                    </Row>
                    <Title level={4}>资源配置建议</Title>
                    <List
                      dataSource={resourceAllocation.resource_suggestions}
                      renderItem={(item: any) => (
                        <List.Item>
                          <Card style={{ width: '100%' }}>
                            <Space>
                              <Tag color={item.priority === '高' ? 'red' : 'orange'}>
                                {item.priority}优先级
                              </Tag>
                              <Text strong>{item.type}</Text>
                              <Text>：{item.count} 个/组</Text>
                            </Space>
                            <div style={{ marginTop: 8 }}>
                              <Text>{item.description}</Text>
                            </div>
                          </Card>
                        </List.Item>
                      )}
                    />
                    <Alert
                      message="总体建议"
                      description={
                        <List
                          dataSource={resourceAllocation.recommendations}
                          renderItem={(item: string) => <List.Item>{item}</List.Item>}
                        />
                      }
                      type="success"
                      style={{ marginTop: 16 }}
                    />
                  </div>
                ) : (
                  <Alert message="暂无数据" type="info" />
                )}
              </Card>
            ),
          },
          {
            key: 'prevention',
            label: (
              <span>
                <SafetyOutlined /> 预防措施建议
              </span>
            ),
            children: (
              <Card>
                {preventionMeasures?.measures && preventionMeasures.measures.length > 0 ? (
                  <div>
                    <List
                      dataSource={preventionMeasures.measures}
                      renderItem={(measure: any) => (
                        <List.Item>
                          <Card style={{ width: '100%' }}>
                            <Space direction="vertical" style={{ width: '100%' }}>
                              <div>
                                <Tag color={measure.priority === '高' ? 'red' : 'orange'}>
                                  {measure.priority}优先级
                                </Tag>
                                <Text strong>{measure.category}</Text>
                              </div>
                              <List
                                dataSource={measure.measures}
                                renderItem={(item: string) => (
                                  <List.Item style={{ padding: '4px 0' }}>
                                    • {item}
                                  </List.Item>
                                )}
                              />
                            </Space>
                          </Card>
                        </List.Item>
                      )}
                    />
                    <Alert
                      message="实施优先级"
                      description={
                        <List
                          dataSource={preventionMeasures.implementation_priority}
                          renderItem={(item: string) => <List.Item>{item}</List.Item>}
                        />
                      }
                      type="success"
                      style={{ marginTop: 16 }}
                    />
                  </div>
                ) : (
                  <Alert message={preventionMeasures?.message || '暂无数据'} type="info" />
                )}
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}

export default Deployment

