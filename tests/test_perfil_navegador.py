"""O perfil do navegador não pode crescer sem teto: caches são podados, o login fica."""

from agente.browser import CACHE_DIRS, trim_profile


def fill(path, mb):
    path.mkdir(parents=True, exist_ok=True)
    (path / "dados").write_bytes(b"x" * (mb * 1024 * 1024))


def test_big_caches_are_removed_and_logins_kept(tmp_path):
    for d in CACHE_DIRS[:3]:
        fill(tmp_path / d, 30)
    fill(tmp_path / "Default" / "IndexedDB", 1)
    (tmp_path / "Default" / "Cookies").write_bytes(b"login")
    assert trim_profile(tmp_path, limit_mb=50) == 90
    assert not any((tmp_path / d).exists() for d in CACHE_DIRS)
    assert (tmp_path / "Default" / "Cookies").read_bytes() == b"login"
    assert (tmp_path / "Default" / "IndexedDB" / "dados").exists()


def test_small_caches_and_missing_profile_are_left_alone(tmp_path):
    fill(tmp_path / CACHE_DIRS[0], 5)
    assert trim_profile(tmp_path, limit_mb=50) == 0 and (tmp_path / CACHE_DIRS[0]).exists()
    assert trim_profile(tmp_path / "nao-existe") == 0
