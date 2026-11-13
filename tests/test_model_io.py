# -*- coding: utf-8 -*-
"""
模型存档的读写契约

模板（注册时的窗口矩阵）与模型存在**同一个文件**里，这条选择带来三条必须
钉住的约束：

1. 存档里要能读出模板，且数值与写入的一致；
2. 模板**不能污染 metadata** —— metadata 一旦混进 ndarray，`weights_only=True`
   会拒绝加载整份存档，等于把模型也一起弄坏；
3. 旧存档（没有模板）读出来必须是 None，不能抛异常 —— 模板是可选能力，
   缺了它只该降级，不该让认证失败。
"""

import numpy as np
import pytest
import torch

from model_example.model_creator import create_model
from model_example.model_io import load_model, load_template, save_model


@pytest.fixture(scope='module')
def model():
    """一个小模型即可：本文件验证的是存档格式，不是训练效果。"""
    created = create_model(input_size=1)
    created.eval()
    return created


@pytest.fixture
def windows():
    """60 个窗口 × 10 点，形状与注册链路的训练矩阵一致。"""
    rng = np.random.default_rng(20261113)
    return rng.normal(0, 1, (60, 10))


def _save(model, tmp_path, template=None, metadata=None):
    path = str(tmp_path / 'user_model.pth')
    assert save_model(model, path, metadata, template=template) is True
    return path


class TestTemplateRoundTrip:
    def test_reads_back_the_same_values(self, model, windows, tmp_path):
        path = _save(model, tmp_path, template=windows)
        loaded = load_template(path)

        assert loaded is not None
        assert loaded.shape == windows.shape
        # 存档是 float32，读回是 float64：逐元素的差异只该来自精度收敛
        assert np.allclose(loaded, windows, atol=1e-6)

    def test_shape_is_recorded_in_metadata(self, model, windows, tmp_path):
        path = _save(model, tmp_path, template=windows)
        checkpoint = torch.load(path, map_location='cpu', weights_only=True)

        assert checkpoint['metadata']['template'] == {
            'windows': 60,
            'window_length': 10,
        }

    def test_template_lives_next_to_state_dict(self, model, windows, tmp_path):
        """不是塞进 metadata，而是同级的一个张量键。"""
        path = _save(model, tmp_path, template=windows)
        checkpoint = torch.load(path, map_location='cpu', weights_only=True)

        assert 'template_windows' in checkpoint
        assert torch.is_tensor(checkpoint['template_windows'])
        # metadata 仍只含基础类型 —— 这是 weights_only 能读的前提
        assert not any(
            isinstance(v, (np.ndarray, torch.Tensor))
            for v in checkpoint['metadata'].values()
        )

    def test_model_loads_normally_with_template(self, model, windows, tmp_path):
        """带上模板后，模型本身仍能正常加载与推理。"""
        path = _save(model, tmp_path, template=windows)
        loaded_model, metadata = load_model(path, torch.device('cpu'))

        assert loaded_model is not None
        assert metadata['template']['window_length'] == 10
        with torch.no_grad():
            out = loaded_model(torch.randn(1, 10, 1))
        assert out.shape == (1, 1)

    def test_tensor_input_is_accepted(self, model, windows, tmp_path):
        """训练矩阵本身就是 tensor，不必让调用方先转成 numpy。"""
        path = _save(model, tmp_path, template=torch.as_tensor(windows))
        loaded = load_template(path)

        assert loaded is not None
        assert np.allclose(loaded, windows, atol=1e-6)


class TestTemplateAbsence:
    def test_no_template_saved(self, model, tmp_path):
        path = _save(model, tmp_path, template=None)

        assert load_template(path) is None
        checkpoint = torch.load(path, map_location='cpu', weights_only=True)
        assert 'template_windows' not in checkpoint
        # 显式写出 None，与「字段缺失」区分开：前者是「这次没存」，
        # 后者是「这份存档格式不认这个字段」
        assert checkpoint['metadata']['template'] is None

    def test_legacy_checkpoint(self, model, tmp_path):
        """模拟旧存档：只有 state_dict 与 metadata，没有模板键。"""
        path = str(tmp_path / 'legacy.pth')
        torch.save(
            {
                'model_state_dict': model.state_dict(),
                'metadata': {'input_size': 1},
            },
            path,
        )

        assert load_template(path) is None
        assert load_model(path, torch.device('cpu'))[0] is not None

    def test_unreadable_file(self, tmp_path):
        """读不出来只该降级，不该把异常抛给调用方。"""
        path = str(tmp_path / 'not_a_checkpoint.pth')
        with open(path, 'wb') as handle:
            handle.write(b'not a torch checkpoint')

        assert load_template(path) is None


class TestTemplateValidation:
    def test_one_dimensional_input_is_rejected(self, model, tmp_path):
        """一维数组通常是被误传的整段信号，存进去会让后续逐窗比对算错。"""
        path = _save(model, tmp_path, template=np.zeros(600))

        assert load_template(path) is None
        assert load_model(path, torch.device('cpu'))[0] is not None

    def test_non_finite_template_is_rejected(self, model, tmp_path):
        bad = np.zeros((3, 10))
        bad[1, 2] = np.nan
        path = _save(model, tmp_path, template=bad)

        assert load_template(path) is None

    def test_empty_template_is_rejected(self, model, tmp_path):
        path = _save(model, tmp_path, template=np.empty((0, 10)))

        assert load_template(path) is None

    def test_rejection_does_not_break_saving(self, model, windows, tmp_path):
        """模板不合法只损失比对能力，模型存档本身必须照常写成。"""
        path = _save(model, tmp_path, template=np.zeros(600))

        loaded_model, metadata = load_model(path, torch.device('cpu'))
        assert loaded_model is not None
        assert metadata['template'] is None
