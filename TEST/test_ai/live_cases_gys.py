"""AI 辅助编写的真实模型测试场景；预期结果在执行前定义。"""
R1 = {'id': 'R1', 'label': 'DS_LS', 'box': [50, 84, 116, 150]}
R2 = {'id': 'R2', 'label': 'DS_LS', 'box': [264, 84, 330, 150]}
OIL = {'id': 'O1', 'label': 'LY', 'box': [160, 150, 236, 212]}


def cases():
    return [
        dict(id='V-A01', title='灰度双螺栓场景与单目标', source='source', targets=[R1], expected=[('R1','DS_LS','generate',0)], bolts=2),
        dict(id='V-A02', title='漏油任务选择漏油参考', source='source', targets=[OIL], expected=[('O1','LY','generate',1)], bolts=2),
        dict(id='V-A03', title='同图两种异常目标不混合', source='source', targets=[R1,OIL], expected=[('R1','DS_LS','generate',0),('O1','LY','generate',1)], bolts=2),
        dict(id='V-A04', title='同标签双ROI分别规划', source='source', targets=[R1,R2], expected=[('R1','DS_LS','generate',0),('R2','DS_LS','generate',0)], bolts=2),
        dict(id='V-A05', title='低亮度输入的目标识别', source='dim', targets=[R1], expected=[('R1','DS_LS','generate',0)], bolts=2),
        dict(id='V-A06', title='参考顺序互换后的语义选择', source='source', targets=[R1], reverse_refs=True, expected=[('R1','DS_LS','generate',1)], bolts=2),
        dict(id='V-A07', title='缺少参考时不虚构参考下标', source='source', targets=[R1], no_refs=True, expected=[('R1','DS_LS','generate',-1)], bolts=2),
        dict(id='V-A08', title='低分辨率输入保持目标绑定', source='small', targets=[R1], expected=[('R1','DS_LS','generate',0)], bolts=2),
        dict(id='V-A09', title='生产批量规划保留双ROI及局部参考索引', source='source', targets=[R1,R2], expected='two independent production plans', bolts=2, production='batch'),
        dict(id='V-A10', title='生产候选比较排除未编辑图片', source='source', targets=[R1], expected='select removal candidate or reject all; never accept unchanged source', bolts=2, production='compare'),
    ]
