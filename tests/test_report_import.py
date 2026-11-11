import shutil
import subprocess
import unittest
from locqa.report import _TEMPLATE


@unittest.skipUnless(shutil.which('node'), 'Node required for JavaScript import tests')
class ReportImportTests(unittest.TestCase):
    def test_import_contract(self):
        functions = _TEMPLATE[_TEMPLATE.index('function prepareImport'): _TEMPLATE.index('function save()')]
        code = functions + r'''
const assert=require('node:assert/strict');
const item={id:'new',key:'x',issue_type:'placeholder_mismatch',source:'Hello {name}',target:'Сәлем'};
const row={id:'old',key:'x',issue_type:item.issue_type,original_source:item.source,original_target:item.target,decision:'edit',final_text:'Сәлем {name}',reviewer:'A',comment:'Контекст',updated_at:'2026-10-31'};
const fresh=()=>Object.create(null);
let result=prepareImport([row],[item],fresh());
assert.equal(result.added,1);
assert.equal(result.decisions.new.comment,'Контекст');
assert.equal(result.decisions.new.reviewer,'A');
assert.equal(result.decisions.new.id,'new');
assert.equal(prepareImport({decisions:[row]},[item],fresh()).added,1);
assert.equal(prepareImport([row],[item],result.decisions).unchanged,1);
assert.equal(prepareImport([row,row],[item],fresh()).added,1);
for(const change of [
  {original_source:'changed'}, {original_target:'changed'}, {key:'unknown'},
  {final_text:'Сәлем'}, {decision:'code',final_text:null}, {decision:'unknown'},
  {comment:42}, {reviewer:42}, {final_text:''}, {updated_at:42},
  {id:'new',key:'wrong'}
]) assert.throws(()=>prepareImport([{...row,...change}],[item],fresh()));
assert.throws(()=>prepareImport({},[item],fresh()));
assert.throws(()=>prepareImport([null],[item],fresh()));
assert.throws(()=>prepareImport([row],[item,{...item,id:'second'}],fresh()));
assert.throws(()=>prepareImport([row,{...row,comment:'different'}],[item],fresh()));
const previous=result.decisions;
const snapshot=JSON.stringify(previous);
assert.throws(()=>prepareImport([{...row,final_text:'Басқа {name}'}],[item],previous));
assert.equal(JSON.stringify(previous),snapshot);
assert.throws(()=>prepareImport([row,{...row,key:'unknown'}],[item],fresh()));
const pending={...row,decision:'pending',final_text:null};
assert.equal(prepareImport([pending],[item],fresh()).decisions.new.status,'pending');
const reject={...row,decision:'reject',final_text:null};
assert.equal(prepareImport([reject],[item],fresh()).decisions.new.edit,null);
const legacy={...row};delete legacy.comment;delete legacy.reviewer;
assert.equal(prepareImport([legacy],[item],fresh()).decisions.new.comment,'');
console.log('Import validation, conflicts, atomicity and metadata: OK');
'''
        result = subprocess.run(['node', '-e', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_comment_and_import_controls(self):
        self.assertIn('id="importFile"', _TEMPLATE)
        self.assertIn('commentDrafts.get(id)', _TEMPLATE)
        self.assertIn("comment: d.comment ?? ''", _TEMPLATE)
        self.assertIn('reviewer: d.reviewer ??', _TEMPLATE)
        self.assertNotIn("fetch('report.json'", _TEMPLATE)

if __name__ == '__main__':
    unittest.main()
