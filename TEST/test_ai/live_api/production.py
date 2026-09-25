"""Live tests of real planner, critic and candidate-selection methods. No mocks."""
from PIL import Image, ImageDraw


def execute(case, client, folder, data):
    folder.mkdir(parents=True, exist_ok=True)
    items=[]
    for i,t in enumerate(case['targets']):
        mask=Image.new('L',(384,256));ImageDraw.Draw(mask).rectangle(t['box'],fill=255)
        path=folder/('mask_'+str(i)+'.png');mask.save(path)
        items.append(dict(roi_id=t['id'],labels=[t['label']],
                          shapes=[dict(label=t['label'],shape_type='rectangle',points=[t['box'][:2],t['box'][2:]])],
                          roi_mask_path=path,focus_mask_path=path,
                          references=[data/'missing_reference.png'],
                          base_prompt='受控灰度机械示意图。移除指定六角螺栓头，露出孔洞，保留垫圈、另一螺栓及全部无关像素。'))
    kind=case['production'];source=data/'source.png'
    if kind in {'batch','duplicate'}:
        try:
            result=client.plan_batch(source,items,folder)
        except ValueError as exc:
            if kind=='duplicate' and not client.requests and ('重复' in str(exc) or 'duplicate' in str(exc).lower()):
                return {'rejected_before_api':True,'reason':str(exc)},[]
            raise
        if kind=='duplicate':
            return result,['D05: duplicate input ROI IDs were accepted; two input tasks collapsed to '+str(len(result))+' plan(s)']
        errors=[]
        if set(result)!={'R1','R2'}: errors.append('production batch lost ROI binding')
        for rid,p in result.items():
            if not p.get('edit_instruction'): errors.append(rid+': empty edit instruction')
            if any(x!=0 for x in p.get('selected_reference_indices',[])): errors.append(rid+': reference index out of range')
            for region in p.get('mask_regions',[]):
                if any(not (0<=x<=384 and 0<=y<=256) for x,y in region.get('points',[])):
                    errors.append(rid+': mask coordinate outside source')
        return result,errors
    if kind=='critic':
        result=client.critique(source,source,source,['DS_LS'],{'edit_instruction':'移除左侧螺栓，右侧保持原样'},folder,[data/'missing_reference.png'])
        return result,[] if result.get('pass') is False else ['unchanged source accepted as anomaly']
    result=client.compare_candidates(source,source,[source,data/'missing_reference.png'],['DS_LS'],
                                    {'edit_instruction':'移除左侧螺栓，保留右侧及背景'},[],folder,[data/'missing_reference.png'])
    errors=[] if result.get('pass') is False or result.get('selected_index')==1 else ['unchanged candidate selected and accepted']
    indices=[row.get('index') for row in result.get('candidate_scores',[]) if isinstance(row,dict)]
    if sorted(indices,key=str)!=[0,1]:
        errors.append('D06: exactly two candidates supplied, but candidate_scores indices='+repr(indices))
    if type(result.get('selected_index')) is not int or result['selected_index'] not in (0,1):
        errors.append('D06: selection outside supplied candidate list')
    return result,errors
