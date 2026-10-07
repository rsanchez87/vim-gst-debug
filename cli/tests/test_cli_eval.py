from gstlog.cli import main


def _case(tmp_path, logfile):
    case = tmp_path / "cases" / "c1"
    case.mkdir(parents=True)
    (case / "gst.log").write_text(open(logfile).read())
    (case / "pipeline.txt").write_text("filesrc location=/x ! fakesink")
    (case / "junit.xml").write_text(
        '<testsuite><testcase name="c1"><failure message="boom"/></testcase></testsuite>')
    exp = tmp_path / "expected.tsv"
    exp.write_text("c1\tno such file|does not exist\n")
    return str(tmp_path / "cases"), str(exp)


def test_eval_normal_and_blind(tmp_path, logfile, capsys):
    cases, exp = _case(tmp_path, logfile)
    assert main(["eval", cases, "--expected", exp, "--provider", "heuristic"]) == 0
    assert main(["eval", cases, "--expected", exp, "--provider", "heuristic", "--blind"]) == 0
    assert capsys.readouterr().out.count("1/1 passed") == 2


def test_eval_without_pipeline_file_does_not_send_a_path(tmp_path, logfile, server, monkeypatch):
    from conftest import completion
    cases, exp = _case(tmp_path, logfile)
    (tmp_path / "cases" / "c1" / "pipeline.txt").unlink()
    server.reply = (200, completion('{"summary":"No such file","confidence":"low","recommendation":"r"}'))
    main(["eval", cases, "--expected", exp, "--provider", "llm", "--preset", "custom",
          "--base-url", server.url, "--model", "m"])
    sent = server.requests[0]["body"]["messages"][1]["content"]
    assert "pipeline.txt" not in sent and "Pipeline:" not in sent
