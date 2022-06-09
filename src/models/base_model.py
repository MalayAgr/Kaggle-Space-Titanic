from __future__ import annotations

import functools
from typing import Any, Protocol, Type

import numpy as np
import optuna
import pandas as pd
import sklearn
from sklearn import metrics


class Classifier(Protocol):
    def fit(self, X, y, *args, **kwargs) -> Classifier:
        ...

    def predict(self, X, *args, **kwargs) -> np.ndarray:
        ...

    def predict_proba(self, X, *args, **kwargs) -> np.ndarray:
        ...


class BaseModel:
    name: str = None
    REGISTRY: dict[str, Type[BaseModel]] = {}

    def __init__(self, train_df: pd.DataFrame, test_df: pd.DataFrame) -> None:
        self.train_df = train_df
        self.test_df = test_df

    def __init_subclass__(cls, **kwargs) -> None:
        if (name := cls.name) is not None:
            BaseModel.REGISTRY[name] = cls

    def preprocess_datasets(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        return self.train_df, self.test_df

    def hyperparameter_search(self, n_trials: int) -> dict[str, Any]:
        train_df, test_df = self.preprocess_datasets()

        objective = self.objective
        objective = functools.partial(objective, train_df=train_df, test_df=test_df)

        sampler = optuna.samplers.TPESampler(seed=42)
        study = optuna.create_study(
            sampler=sampler,
            pruner=optuna.pruners.HyperbandPruner(),
            direction="maximize",
        )

        v = optuna.logging.get_verbosity()
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        study.optimize(objective, n_trials=n_trials)

        optuna.logging.set_verbosity(v)

        return study.best_params

    def objective(
        self, trial: optuna.Trial, train_df: pd.DataFrame, test_df: pd.DataFrame
    ) -> float:
        raise NotImplementedError("Base classes need to implement objective().")

    def init_classifier(self, params: dict[str, Any]) -> Classifier:
        raise NotImplementedError("Base classes need to implement init_classifier().")

    def extra_fit_parameters(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return {}

    def _train_fold(
        self,
        df: pd.DataFrame,
        test_df: pd.DataFrame,
        fold: int,
        params: dict[str, Any],
        drop: list[str],
        *,
        verbose: bool = True,
    ) -> tuple[np.ndarray, float]:
        train = df[df["kfold"] != fold]

        y_train = train["Transported"]
        X_train = train.drop(drop, axis=1)

        val = df[df["kfold"] == fold]

        y_val = val["Transported"]
        X_val = val.drop(drop, axis=1)

        clf = self.init_classifier(params=params)

        fit_params = self.extra_fit_parameters(
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            params=params,
        )

        clf.fit(
            X=X_train,
            y=y_train,
            **fit_params,
        )

        val_pred = clf.predict(X_val)
        acc = metrics.accuracy_score(y_val, val_pred)

        if verbose is True:
            print(f"\tFold {fold + 1} - Accuracy = {acc: .4f}")

        df.loc[val.index, "preds"] = clf.predict_proba(X_val)[:, 1]

        return clf.predict_proba(test_df)[:, 1], acc

    def train(
        self,
        df: pd.DataFrame,
        test_df: pd.DataFrame,
        params: dict[str, Any],
        *,
        verbose: bool = True,
    ) -> tuple[np.ndarray, np.ndarray, float]:
        df = df.copy()
        test_df = test_df.drop("PassengerId", axis=1)

        df["preds"] = pd.NA

        drop = ["Transported", "preds", "kfold"]

        total_acc, test_preds = 0.0, []

        for fold in range(5):
            test_pred, acc = self._train_fold(
                df=df,
                test_df=test_df,
                fold=fold,
                params=params,
                drop=drop,
                verbose=verbose,
            )

            total_acc += acc
            test_preds.append(test_pred)

        acc = total_acc / 5

        if verbose is True:
            print(f"\tOverall accuracy = {acc: .4f}")

        test_preds = np.vstack(test_preds)
        test_preds = np.mean(test_preds, axis=0)

        return df["preds"].values, test_preds, acc


class BaseOptunaCVModel(BaseModel):
    pass